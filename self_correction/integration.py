"""
Wires Self-Refine and Reflexion into the SAME DAG/Node execution model
`planning/dag.py` and `planning/dynamic_decomposition.py` already use --
no parallel execution engine, no duplicated tool-calling logic.

`Node.suggested_method` (planning/dag.py) is already populated by the
decomposition layer today with "PS" / "ToT" / "LATS" / None (see
planning/README.md: "'PS' for the deterministic prerequisite check, null
for the mechanical enroll step"). This module adds two more values that
layer -- or a human, or the router in a later slice -- can suggest:

    "SelfRefine"  -> route the node through self_refine.SelfRefine
    "Reflexion"   -> route the node through reflexion.Reflexion
    anything else -> unchanged: call the real tool directly from
                      TOOL_REGISTRY, exactly like today

Every correction run is logged onto the DAG's own trace (`dag.log_event`,
`dag.llm_calls`, `dag.total_tokens`) so a self-correction run shows up in
`artifacts/<method>_<run_id>.json` the same way a decomposition run does --
one trace format for the whole project, not a second one for this slice.
"""
from __future__ import annotations

from planning.dag import DAG, Node
from planning.db_tools import TOOL_REGISTRY

from self_correction.environment import Environment, GroundedEnvironment
from self_correction.self_refine import SelfRefine
from self_correction.reflexion import Reflexion, ReflexionMemory


def execute_node(node: Node, dag: DAG, llm, *, grounded: bool = True,
                  reflexion_memory: ReflexionMemory = None) -> dict:
    """Executes one Node the way dag-based execution always has (direct
    tool call) UNLESS its suggested_method asks for a correction loop, in
    which case that loop's OWN evaluation environment is used instead of
    a single blind tool call.

    `grounded` selects which Environment backs the correction loop --
    this is the one flag `self_correction_evaluation/` flips to produce
    the grounded-vs-ungrounded comparison.
    """
    node.status = "running"

    environment = GroundedEnvironment(llm) if grounded else Environment(llm)
    task = node.to_dict()

    if node.suggested_method == "SelfRefine":
        result = SelfRefine(llm, environment).run(task)
        node.result = result.final_candidate
        node.status = "done" if result.converged else "failed"
        dag.llm_calls += result.llm_calls
        dag.total_tokens += result.total_tokens
        dag.log_event(
            "self_refine", task_id=node.task_id, grounded=grounded,
            iterations=result.iterations, converged=result.converged,
        )
        return node.result

    if node.suggested_method == "Reflexion":
        memory = reflexion_memory or ReflexionMemory()
        result = Reflexion(llm, environment, memory=memory).run(task, task_key=node.tool)
        node.result = result.final_candidate
        node.status = "done" if result.success else "failed"
        dag.llm_calls += result.llm_calls
        dag.total_tokens += result.total_tokens
        dag.log_event(
            "reflexion", task_id=node.task_id, grounded=grounded,
            trials=len(result.trials), success=result.success,
            reflections=[t.reflection for t in result.trials if t.reflection],
        )
        return node.result

    # Unchanged default path: same direct tool call dynamic_decomposition.py
    # already makes -- this slice never touches the deterministic path.
    handler = TOOL_REGISTRY[node.tool]
    try:
        node.result = handler(**node.tool_args)
        node.status = "done"
    except Exception as e:
        node.result = {"status": "error", "message": str(e)}
        node.status = "failed"
    dag.log_event("node_executed", task_id=node.task_id, status=node.status, result=node.result)
    return node.result


def run_dag_with_correction(dag: DAG, llm, *, grounded: bool = True) -> DAG:
    """Executes every node of an already-built DAG in topological order,
    routing each through execute_node(). One ReflexionMemory is shared
    across the whole run so a reflection learned on an earlier node
    (e.g. "check retake policy before assuming failure = ineligible
    forever") is available to a later node of the same tool type."""
    memory = ReflexionMemory()
    for task_id in dag.topological_order():
        node = dag.nodes[task_id]
        execute_node(node, dag, llm, grounded=grounded, reflexion_memory=memory)
    return dag
