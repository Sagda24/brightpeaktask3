"""
Durable checkpointing.

Design choice: we do NOT keep run state in memory or in a log file written
after the fact. Every meaningful transition (a node finishing, a HITL pause
opening, a ticket opening, a resume) is written as a new row in
graph_checkpoints inside the SAME brightpeak.db the rest of the system
already uses — no parallel database.

We append rather than overwrite, so the full history of a run is inspectable
by an admin on the platform ("show the graph's persisted state at the point
it paused or failed"), and `latest()` is just "the last row for this run_id".
"""

import json
import os
import sqlite3
import time

DB_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "DB", "db", "brightpeak.db"
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS graph_checkpoints (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL,
    graph_name  TEXT NOT NULL,
    state       TEXT NOT NULL,
    context     TEXT NOT NULL,   -- JSON blob of the run's accumulated state
    status      TEXT NOT NULL,   -- running | waiting_hitl | ticket_open | done
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_checkpoints_run_id ON graph_checkpoints(run_id);
"""


class CheckpointStore:
    """One row per transition. `latest(run_id)` == the current state of a run."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._ensure_schema()

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self):
        conn = self._conn()
        conn.executescript(_SCHEMA)
        conn.commit()
        conn.close()

    def write(self, run_id: str, graph_name: str, state: str, context: dict, status: str):
        conn = self._conn()
        conn.execute(
            "INSERT INTO graph_checkpoints (run_id, graph_name, state, context, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, graph_name, state, json.dumps(context), status, time.time()),
        )
        conn.commit()
        conn.close()

    def latest(self, run_id: str):
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM graph_checkpoints WHERE run_id = ? ORDER BY seq DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        conn.close()
        if row is None:
            return None
        d = dict(row)
        d["context"] = json.loads(d["context"])
        return d

    def history(self, run_id: str):
        """Full checkpoint history for a run — what the admin panel shows
        when inspecting a paused/failed run."""
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM graph_checkpoints WHERE run_id = ? ORDER BY seq ASC",
            (run_id,),
        ).fetchall()
        conn.close()
        out = []
        for row in rows:
            d = dict(row)
            d["context"] = json.loads(d["context"])
            out.append(d)
        return out
