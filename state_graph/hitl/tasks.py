"""
Human-in-the-loop tasks.

A HITL task is an EXPECTED pause: a node decided, on purpose, that it is not
allowed to make a call by itself (an amount above a threshold, an action
that would contradict a written policy, an irreversible action). This is a
different code path from recovery/tickets.py, which is for UNPLANNED
failures. Keeping them in separate tables with separate statuses is what
lets a grader (or an admin on the platform) tell the two apart.

open()    is called by a graph node (via engine.HITLRequired) when a policy
          condition fires.
resolve() is called by the admin surface of platform/ when a real admin
          clicks "approve" / "reject" / "override" on a pending task — never
          by the graph itself.
"""

import json
import os
import sqlite3
import time
from typing import Optional

from state_graph.checkpointing.store import DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS hitl_tasks (
    id           TEXT PRIMARY KEY,
    run_id       TEXT NOT NULL,
    graph_name   TEXT NOT NULL,
    state        TEXT NOT NULL,
    kind         TEXT NOT NULL DEFAULT 'hitl',  -- 'hitl' (admin decision) or
                                                 -- 'external' (external system event)
    reason       TEXT NOT NULL,   -- WHY the agent isn't allowed to decide alone,
                                   -- or WHAT external event this is waiting on
    payload      TEXT NOT NULL,   -- JSON: whatever the admin needs to see to decide
    status       TEXT NOT NULL,   -- open | resolved
    decision     TEXT,            -- JSON: the admin's decision / the event payload
    created_at   REAL NOT NULL,
    resolved_at  REAL
);
"""


class HITLStore:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        conn = sqlite3.connect(self.db_path)
        conn.executescript(_SCHEMA)
        conn.commit()
        conn.close()

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def open(self, run_id: str, graph_name: str, state: str, reason: str, payload: dict, kind: str = "hitl") -> str:
        task_id = f"{kind}_{run_id}_{state}_{int(time.time() * 1000)}"
        conn = self._conn()
        conn.execute(
            "INSERT INTO hitl_tasks (id, run_id, graph_name, state, kind, reason, payload, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?)",
            (task_id, run_id, graph_name, state, kind, reason, json.dumps(payload), time.time()),
        )
        conn.commit()
        conn.close()
        return task_id

    def resolve(self, run_id: str, state: str, decision: dict, kind: str = "hitl"):
        """Called after the engine has already applied the decision — this
        just marks the most recent open task for this run/state as closed."""
        conn = self._conn()
        conn.execute(
            "UPDATE hitl_tasks SET status = 'resolved', decision = ?, resolved_at = ? "
            "WHERE run_id = ? AND state = ? AND kind = ? AND status = 'open'",
            (json.dumps(decision), time.time(), run_id, state, kind),
        )
        conn.commit()
        conn.close()

    def list_open(self, kind: Optional[str] = None):
        """What the admin panel's HITL inbox (kind='hitl') and the platform's
        'waiting on external system' view (kind='external') each query."""
        conn = self._conn()
        if kind:
            rows = conn.execute(
                "SELECT * FROM hitl_tasks WHERE status = 'open' AND kind = ? ORDER BY created_at ASC", (kind,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM hitl_tasks WHERE status = 'open' ORDER BY created_at ASC").fetchall()
        conn.close()
        return [dict(r) for r in rows]
