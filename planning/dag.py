from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


class DAGCycleError(Exception):
    """Raised when adding a node/edge would make the graph cyclic."""


@dataclass
class Node:
    task_id: str
    instruction: str                     # human-readable description of the sub-task
    tool: str                            # name of the registered handler that executes it
    tool_args: dict = field(default_factory=dict)
    depends_on: list = field(default_factory=list)   # list[task_id]
    suggested_method: Optional[str] = None  # "PS" | "ToT" | "LATS" | None (deterministic)
    status: str = "pending"              # pending -> running -> done | failed | skipped
    result: Any = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


class DAG:
    """
    A directed acyclic graph of Nodes, keyed by task_id.

    Cycle enforcement happens at construction time (add_node), not at
    execution time — a plan that could deadlock never becomes
    executable in the first place.
    """

    def __init__(self, request: dict, method: str):
        self.run_id = str(uuid.uuid4())[:8]
        self.request = request          # the original request this DAG serves
        self.method = method            # "decomposition_first" | "dynamic"
        self.nodes: dict = {}           # task_id -> Node
        self.order: list = []           # insertion order, for readable traces
        self.events: list = []          # free-form trace events (replans, critiques, etc.)
        self.llm_calls = 0
        self.total_tokens = 0
        self.created_at = time.time()

    # ---------------------------------------------------------------- #
    # construction
    # ---------------------------------------------------------------- #
    def add_node(self, node: Node) -> None:
        if node.task_id in self.nodes:
            raise ValueError(f"duplicate task_id: {node.task_id}")

        for dep in node.depends_on:
            if dep not in self.nodes:
                raise ValueError(
                    f"node '{node.task_id}' depends on unknown task '{dep}' "
                    f"(nodes must be added in an order where dependencies "
                    f"already exist)"
                )

        self.nodes[node.task_id] = node
        self.order.append(node.task_id)

        # Cycle check: attempting a full topological sort after every
        # insertion is O(V+E) per insertion and keeps the invariant
        # "this DAG is always acyclic" true at every point in time,
        # not just at the end of construction.
        try:
            self.topological_order()
        except DAGCycleError:
            # roll back the just-added node so the DAG is left in the
            # last valid state, then re-raise
            del self.nodes[node.task_id]
            self.order.pop()
            raise

    def add_edge(self, from_task: str, to_task: str) -> None:
        """Add an extra dependency (to_task depends on from_task) after
        both nodes already exist, re-checking acyclicity."""
        if from_task not in self.nodes or to_task not in self.nodes:
            raise ValueError("both nodes must exist before adding an edge")
        node = self.nodes[to_task]
        if from_task not in node.depends_on:
            node.depends_on.append(from_task)
        try:
            self.topological_order()
        except DAGCycleError:
            node.depends_on.remove(from_task)
            raise

    # ---------------------------------------------------------------- #
    # ordering / validation
    # ---------------------------------------------------------------- #
    def topological_order(self) -> list:
        """Kahn's algorithm. Raises DAGCycleError if a cycle exists."""
        in_degree = {tid: 0 for tid in self.nodes}
        for node in self.nodes.values():
            for dep in node.depends_on:
                in_degree[node.task_id] += 1

        # queue of nodes with no unresolved dependency, in insertion
        # order for determinism
        queue = [tid for tid in self.order if in_degree[tid] == 0]
        result = []

        # adjacency: dep -> [nodes that depend on it]
        dependents: dict = {tid: [] for tid in self.nodes}
        for node in self.nodes.values():
            for dep in node.depends_on:
                dependents[dep].append(node.task_id)

        while queue:
            tid = queue.pop(0)
            result.append(tid)
            for dependent in dependents[tid]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if len(result) != len(self.nodes):
            remaining = set(self.nodes) - set(result)
            raise DAGCycleError(
                f"cycle detected among tasks: {sorted(remaining)}"
            )
        return result

    # ---------------------------------------------------------------- #
    # trace / evidence
    # ---------------------------------------------------------------- #
    def log_event(self, kind: str, **payload) -> None:
        self.events.append({"t": time.time(), "kind": kind, **payload})

    def to_trace(self) -> dict:
        return {
            "run_id": self.run_id,
            "method": self.method,
            "request": self.request,
            "nodes": [self.nodes[tid].to_dict() for tid in self.order],
            "topological_order": self._safe_topo(),
            "events": self.events,
            "llm_calls": self.llm_calls,
            "total_tokens": self.total_tokens,
            "created_at": self.created_at,
        }

    def _safe_topo(self):
        try:
            return self.topological_order()
        except DAGCycleError:
            return None

    def save_trace(self, artifacts_dir: str = "artifacts") -> str:
        import os
        os.makedirs(artifacts_dir, exist_ok=True)
        path = os.path.join(
            artifacts_dir, f"{self.method}_{self.run_id}.json"
        )
        with open(path, "w") as f:
            json.dump(self.to_trace(), f, indent=2, default=str)
        return path
