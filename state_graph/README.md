# state_graph/ — Brightpeak Academy state-graph agents

Three new agents, sitting next to the existing `memory/`+`rag/` agent and the
existing `planning/` (decomposition) agent, reusing the same
`DB/db/brightpeak.db` and meant to be driven from the same
`Mcp-Server/server.py`. Nothing here stands up a parallel database or a
parallel server — `checkpointing/store.py`, `hitl/tasks.py`, and
`recovery/tickets.py` all write into the existing SQLite file via
`CREATE TABLE IF NOT EXISTS`.

## Why a state graph and not a for-loop / try-except

Every state graph here has all three of: a real multi-sitting wait on
something outside the agent's control, a real branch that depends on a
human decision or an external reply, and a real failure mode a single retry
cannot fix. None of them re-skin `planning/`'s scheduling problem or
`rag/`'s retrieval problem — they're new agent scope entirely (academic
probation, grade appeals, certificate compliance).

## The three graphs

### 1. `graph_1/` — Academic Probation Multi-Term Monitoring

- **Spans more than one sitting:** a student is tracked across several
  terms, not one run.
- **Real external branch:** a term's grades are posted by instructors
  through `update_student_grade`, on their own schedule — the graph
  genuinely waits (`MONITOR_TERM`, `WaitForExternalEvent`) for that.
- **Real unfixable failure:** if a term ends and grades never post (a
  registrar feed breaks), retrying the same read forever doesn't help —
  it's a ticket for a person to chase.
- **Real human decision (HITL):** `ADVISOR_SIGNOFF` — the agent may never
  change a student's official intervention-plan status, or recommend
  dismissal, on its own.
- **Cycle:** `EVALUATE_TERM → ADVISOR_SIGNOFF → (continue) → MONITOR_TERM`
  revisits an already-visited state for the next term, same `run_id`.
- **Two techniques:**
  - *Task decomposition* (`BUILD_INTERVENTION_PLAN`) — the plan's shape
    (tutoring referral? reduced load?) depends on *why* this student is at
    risk, not a fixed template.
  - *RAG* (`FETCH_POLICY`) — the actual probation thresholds live in
    `rag/knowledge_base/knowledge_base.json` (the same knowledge base the
    real RAG agent uses), not in a table this agent can `SELECT`.

### 2. `graph_2/` — Grade Dispute & Appeal Escalation

- **Spans more than one sitting:** waits on an instructor's reply, then —
  if it escalates — a committee's reply.
- **Real external branch + cycle:** the committee can approve, deny, or
  **remand** the appeal for more evidence, looping back to
  `CHOOSE_APPEAL_STRATEGY` with new evidence in context — a real revisit.
- **Real unfixable failure:** a malformed/unrecognized instructor or
  committee response isn't something a retry fixes — it's a ticket. Proven
  in testing: an `AWAIT_COMMITTEE_DECISION` response of
  `{"decision": "nonsense_value"}` opens a ticket at that exact state; once
  an admin supplies the corrected response via `resume_from_ticket(...,
  fix={...})`, the run continues from `AWAIT_COMMITTEE_DECISION` straight
  through to `DONE_APPROVED` — not from `SUBMIT_DISPUTE`.
- **Real human decision (HITL):** `HITL_REGISTRAR_SIGNOFF` — any grade
  change above `GRADE_CHANGE_HITL_THRESHOLD` (10 points) requires a
  registrar's sign-off, even after committee approval. This is a stricter
  bar than `update_student_grade`'s own role check, which only blocks
  *who* can write, not *how large* a change can be applied unattended.
- **Two techniques:**
  - *Tree of Thoughts* (`CHOOSE_APPEAL_STRATEGY`) — a handful of mutually
    exclusive appeal arguments (grading error / extenuating circumstances /
    attendance dispute); picking the wrong one burns a real, limited appeal
    window, so branches are scored before one is committed to.
  - *Constrained ReAct* (`FILE_APPEAL`, `APPLY_GRADE_CHANGE`) — both nodes
    may only call a fixed whitelist (`WHITELISTED_ACTIONS`), and
    `_act_update_student_grade` enforces exactly the same role/range checks
    `Mcp-Server/server.py`'s live `update_student_grade` tool does.

### 3. `graph_3/` — Certificate Issuance with Compliance Hold Resolution

- **Real external branch:** eligibility depends on financial/disciplinary
  holds set by other offices, which can be waived mid-run by a person who
  isn't the agent.
- **Real unfixable failure:** a missing student record, or a duplicate
  certificate write (`UNIQUE constraint failed: certificates.enrollment_id`
  — an actual bug this build surfaced and now handles as a ticket instead
  of crashing the process) both become tickets, not silent failures.
- **Real human decision + irreversible action (HITL, twice):**
  `HITL_REGISTRAR_HOLD_REVIEW` — a hold may never be waived by the agent —
  and `HITL_FINAL_SIGNOFF` — issuing a certificate can't be un-sent, so
  sign-off is required even when every check comes back clean.
- **Cycle:** `ATTEMPT_AUTO_RESOLVE → RUN_ELIGIBILITY_CHECKS` and
  `HITL_REGISTRAR_HOLD_REVIEW → RUN_ELIGIBILITY_CHECKS` both re-run the
  *full* eligibility search after anything changes, rather than trusting a
  stale partial result.
- **Two techniques:**
  - *LATS* (`RUN_ELIGIBILITY_CHECKS`) — searches candidate orderings of
    `CHECKS` and scores each against a real eligibility rubric (credits,
    financial hold, disciplinary hold, prerequisites), not the model's own
    opinion of what "looks eligible."
  - *Constrained ReAct* (`ATTEMPT_AUTO_RESOLVE`, `ISSUE_CERTIFICATE`) — the
    only whitelisted actions are `recheck_financial_hold` and
    `issue_certificate`; the latter can never run except after
    `HITL_FINAL_SIGNOFF`.

## How HITL and tickets are actually different code paths

`engine.py` has three distinct pause outcomes, not two, because "wait on
something outside the model" splits into two genuinely different cases the
brief also calls out:

| | Raised by a node when... | Resolved by | Table / status |
|---|---|---|---|
| `HITLRequired` | a **written policy** says a human must decide (threshold, irreversible action) | an admin, through the platform, calling `resume_from_hitl(run_id, decision)` | `hitl_tasks`, `kind='hitl'` |
| `WaitForExternalEvent` | the graph is waiting on an **external system**, not a decision (instructor reply, committee reply, term grades posting) | a webhook/adapter calling `resume_from_external_event(run_id, event_data)` | `hitl_tasks`, `kind='external'` |
| any other `Exception` | something **broke** — a bad DB write, an unparseable response, a whitelist violation | an admin, through the platform, calling `resume_from_ticket(run_id, ticket_id, fix=...)` after investigating | `tickets` |

All three are caught in exactly one place — `StateGraph._advance()` — so a
grader can find every HITL node and every ticket-producing failure by
searching for `HITLRequired` / `raise Exception` calls inside `graph.py`,
without reading the whole engine.

## Checkpointing

`checkpointing/store.py` appends one row to `graph_checkpoints` per
transition — after every node finishes, after every pause opens, after
every resume. `latest(run_id)` is just "the newest row for this run,"
`history(run_id)` is the full audit trail an admin sees when inspecting a
paused/failed run on the platform.

**Proven, not asserted:** `demo_crash_resume.py` starts
`graph_1`, and `BUILD_INTERVENTION_PLAN` calls `os._exit(137)`
mid-node (a real, hard process kill — gated on `SIMULATE_CRASH=1`, set only
by the `start` subcommand, never by `resume`, so the resuming process can't
re-trigger it). A brand-new `python3` process then calls
`graph.resume(run_id)` and picks up from the last checkpoint — `INTAKE` is
not re-executed, no context collected before the kill is lost. Run it
yourself:

```bash
python -m state_graph.demo_crash_resume start
python -m state_graph.demo_crash_resume history <run_id>   # shows the state right before the kill
python -m state_graph.demo_crash_resume resume <run_id>
python -m state_graph.demo_crash_resume history <run_id>   # shows it continued from there
```

## What's still a stand-in (and exactly where to swap it)

To keep this runnable without network access, an API key, or `fastmcp` /
`langgraph` installed:

- ToT/LATS "scoring" and task decomposition use small deterministic
  heuristics instead of a real LLM call. Every such spot is commented
  `# Real LLM call would be...` at the exact line to replace — the node
  boundary and the shape of the output (ranked candidates, an ordered task
  list) is what a real call would also produce.
- `_lightweight_retrieve()` in `graph_1/graph.py` is a keyword
  stand-in for `rag/hybrid_rag.py`'s real FAISS-based retrieval, reading
  the exact same `knowledge_base.json`.
- `resume_from_hitl` / `resume_from_external_event` are called directly in
  tests here; on the real platform these are the two calls the admin
  surface and the external-event webhook adapter make.

## Known gap to close with Person 2 (DB/platform integration)

The whitelisted actions in `graph_2/graph.py` and
`graph_3/graph.py` currently open their own `sqlite3`
connections directly against `DB/db/brightpeak.db`. Once the MCP server
supports the runtime tool registration the platform needs, these should
call through the live `mcp` client the same way a chat-driven agent would,
instead of hitting the DB file directly — the validation logic (role
checks, grade ranges) is already written to match `update_student_grade`
exactly, so that swap should be mechanical.
