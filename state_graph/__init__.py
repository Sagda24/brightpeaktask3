"""
state_graph/ — the three state-graph agents for Brightpeak Academy.

This package sits next to the existing memory/RAG agent (memory/, rag/) and
the existing decomposition/planning agent (planning/), reuses the same
SQLite database (DB/db/brightpeak.db) via checkpointing/store.py, and is
meant to be driven from the same MCP server (Mcp-Server/server.py) and the
platform/ product surface.

Sub-packages:
    engine.py        generic, dependency-free state-graph runner shared by
                      all three graphs (cycles, checkpoints, HITL, tickets).
    checkpointing/    durable checkpoint store (SQLite).
    hitl/             human-in-the-loop task store, resolved by an admin
                      through platform/.
    recovery/         ticket store for unplanned mid-node failures.
    graph_1/    Academic Probation Multi-Term Monitoring.
    graph_2/ Grade Dispute & Appeal Escalation.
    graph_3/  Certificate Issuance with Compliance Hold Resolution.

See state_graph/README.md for the rationale behind each graph, the two LLM
techniques wired into each one, and where the HITL/ticket paths diverge.
"""
