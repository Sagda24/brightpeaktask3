"""
Failure tickets.

A ticket is UNPLANNED: a tool call errored, a DB row was missing, an external
response came back malformed, a schema check failed. The graph did not
choose to stop — it broke. That is the entire difference from hitl/tasks.py,
which is an expected pause the graph chose on purpose.

open()    is called by engine.StateGraph._loop() automatically, whenever a
          node raises anything other than HITLRequired. Never called by
          application code directly, and never inserted by hand for a demo —
          it only exists because a real exception was caught.
resolve() is called by an admin through platform/ after they've looked at
          the persisted checkpoint (checkpointing/store.py) for this run and
          fixed whatever was wrong (e.g. patched a record, waited out an
          external outage). Resolving a ticket does not replay the run from
          the start — engine.resume_from_ticket() re-enters at the exact
          state that failed.
"""

import json
import sqlite3
import time

from state_graph.checkpointing.store import DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id            TEXT PRIMARY KEY,
    run_id        TEXT NOT NULL,
    graph_name    TEXT NOT NULL,
    state         TEXT NOT NULL,   -- the node that was mid-execution when it broke
    error         TEXT NOT NULL,
    traceback     TEXT NOT NULL,
    status        TEXT NOT NULL,   -- open | investigating | resolved
    created_at    REAL NOT NULL,
    resolved_at   REAL
);
"""


class TicketStore:
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

    def open(self, run_id: str, graph_name: str, state: str, error: str, traceback: str) -> str:
        ticket_id = f"tkt_{run_id}_{state}_{int(time.time() * 1000)}"
        conn = self._conn()
        conn.execute(
            "INSERT INTO tickets (id, run_id, graph_name, state, error, traceback, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'open', ?)",
            (ticket_id, run_id, graph_name, state, error, traceback, time.time()),
        )
        conn.commit()
        conn.close()
        return ticket_id

    def set_status(self, ticket_id: str, status: str):
        assert status in ("open", "investigating", "resolved")
        conn = self._conn()
        conn.execute("UPDATE tickets SET status = ? WHERE id = ?", (status, ticket_id))
        conn.commit()
        conn.close()

    def resolve(self, ticket_id: str):
        conn = self._conn()
        conn.execute(
            "UPDATE tickets SET status = 'resolved', resolved_at = ? WHERE id = ?",
            (time.time(), ticket_id),
        )
        conn.commit()
        conn.close()

    def list_open(self):
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM tickets WHERE status != 'resolved' ORDER BY created_at ASC"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def find_open_for_run(self, run_id: str):
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM tickets WHERE run_id = ? AND status != 'resolved' "
            "ORDER BY created_at DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        conn.close()
        return dict(row) if row else None
