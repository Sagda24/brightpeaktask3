"""
Graph 1 — Academic Probation Multi-Term Monitoring

WHY THIS NEEDS A STATE GRAPH (not a for-loop / try-except):
- Spans multiple terms: a student is monitored across several terms, not one
  sitting. The run genuinely has to still be "live" weeks or months later.
- Real branch outside the model's control: a term's final grades are posted
  by instructors through update_student_grade — an external actor on their
  own schedule, not something the agent can retry into existing.
- Real failure a single retry can't fix: if a term ends and grades never
  post (a registrar feed breaks, an instructor never submits), retrying the
  same DB read forever fixes nothing — that's a ticket for a person to chase.
- Real human decision: any change to a student's official intervention plan,
  and any recommendation to dismiss a student, must be signed off by an
  advisor. The agent is not allowed to decide either on its own.

TWO LLM-CALL TECHNIQUES USED, AND WHY THIS NODE NEEDED IT:
- Task decomposition (BUILD_INTERVENTION_PLAN): an intervention isn't one
  action, it's an ordered sequence (tutoring referral -> reduced course load
  -> mandatory check-ins) that depends on which policy triggers fired for
  THIS student — decomposition is the right tool because the plan's shape
  changes per student, not because the plan is long.
- RAG (FETCH_POLICY): the actual thresholds ("2 consecutive terms below
  policy GPA" etc.) live in the Academic Warning Policy document, not in any
  database row the agent can just SELECT — the agent has to ground its plan
  in that unstructured policy text, which is exactly what RAG is for.

Cycle: EVALUATE_TERM -> ADVISOR_SIGNOFF -> (approved) -> MONITOR_TERM again,
for the next term. This is a real revisit of an earlier state, not a fresh
run — the same run_id keeps its full history across terms.
"""

import json
import sqlite3
from pathlib import Path

from state_graph.engine import HITLRequired, Node, StateGraph, WaitForExternalEvent
from state_graph.checkpointing.store import DB_PATH

KB_PATH = Path(__file__).resolve().parents[2] / "rag" / "knowledge_base" / "knowledge_base.json"

PROBATION_GPA_THRESHOLD = 70.0  # policy-defensible bar for "at risk", grades are 0-100 here
MAX_TERMS_MONITORED = 3


def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _lightweight_retrieve(query: str, top_k: int = 2):
    """Stand-in for rag/hybrid_rag.py's real retrieval (which needs faiss +
    an embedding model that aren't guaranteed to be installed everywhere
    this graph runs). Swap this for rag.hybrid_rag.hybrid_search(...) once
    running behind the live MCP server with its full dependency set — the
    node boundary (FETCH_POLICY) doesn't change either way. Uses the SAME
    knowledge_base.json the real RAG agent uses, not a parallel copy."""
    docs = json.loads(KB_PATH.read_text(encoding="utf-8"))
    terms = set(query.lower().split())
    scored = []
    for doc in docs:
        text = (doc.get("title", "") + " " + doc.get("text", "")).lower()
        score = sum(text.count(t) for t in terms)
        if score:
            scored.append((score, doc))
    scored.sort(key=lambda x: -x[0])
    return [d for _, d in scored[:top_k]]


# ---------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------

def intake(context: dict) -> str:
    conn = _db()
    rows = conn.execute(
        "SELECT c.title, e.grade FROM enrollments e JOIN courses c ON e.course_id = c.course_id "
        "WHERE e.student_id = ? AND e.status = 'COMPLETED'",
        (context["student_id"],),
    ).fetchall()
    conn.close()

    if not rows:
        raise Exception(f"No completed enrollments found for student_id={context['student_id']}")

    grades = [r["grade"] for r in rows if r["grade"] is not None]
    avg = sum(grades) / len(grades) if grades else 0.0
    context["term_average"] = avg
    context["terms_monitored"] = context.get("terms_monitored", 0)
    context["history"] = context.get("history", [])

    if avg >= PROBATION_GPA_THRESHOLD and not context.get("_force_flag_for_demo"):
        context["history"].append({"event": "intake_ok", "average": avg})
        return "DONE_NOT_ELIGIBLE"

    context["history"].append({"event": "intake_flagged", "average": avg})
    return "BUILD_INTERVENTION_PLAN"


def build_intervention_plan(context: dict) -> str:
    # --- Task decomposition ---
    # Real LLM call would be: llm("decompose an intervention plan for a
    # student averaging {avg} given trigger reasons {...}"). Deterministic
    # stand-in below keeps the demo reproducible without an API key, but the
    # node boundary and the shape of the output (an ordered task list) is
    # exactly what a real decomposition call would return.
    avg = context["term_average"]
    plan = ["schedule_advisor_checkin"]
    if avg < 60.0:
        plan += ["mandatory_tutoring_referral", "reduce_course_load"]
    else:
        plan += ["recommended_tutoring_referral"]
    plan.append("re_evaluate_next_term")
    context["plan"] = plan
    context["history"].append({"event": "plan_built", "plan": plan})

    import os
    if os.environ.get("SIMULATE_CRASH") == "1":
        # Demo hook only — see demo_crash_resume.py. Simulates the process
        # being killed mid-node, AFTER intake's checkpoint was already
        # durably written, to prove that checkpoint is not lost or redone.
        # Gated on an env var (set only by the "start" subcommand, never by
        # "resume") rather than on persisted context, so the fresh process
        # that resumes this run does not crash itself again.
        print("[demo] simulating a hard process kill inside BUILD_INTERVENTION_PLAN...")
        os._exit(137)

    return "FETCH_POLICY"


def fetch_policy(context: dict) -> str:
    # --- RAG ---
    hits = _lightweight_retrieve("academic warning probation grades threshold")
    context["policy_snippets"] = [{"id": d["id"], "title": d["title"]} for d in hits]
    context["history"].append({"event": "policy_fetched", "docs": context["policy_snippets"]})
    return "MONITOR_TERM"


def monitor_term(context: dict) -> str:
    # Genuine wait: nothing to do until the term ends and grades post. That
    # is an external event (instructors calling update_student_grade over
    # the term), not something this node can produce by looping.
    if not context.get("term_grades_posted"):
        raise WaitForExternalEvent(
            reason="waiting for this term's final grades to post",
            payload={"student_id": context["student_id"], "term": context.get("term")},
        )
    return "EVALUATE_TERM"


def _on_term_grades_posted(context: dict, event_data: dict) -> str:
    context["term_grades_posted"] = True
    context["latest_term_average"] = event_data.get("term_average", context["term_average"])
    context["history"].append({"event": "grades_posted", "average": context["latest_term_average"]})
    return "EVALUATE_TERM"


def evaluate_term(context: dict) -> str:
    context["terms_monitored"] += 1
    improved = context["latest_term_average"] >= PROBATION_GPA_THRESHOLD
    context["_last_eval"] = {
        "improved": improved,
        "average": context["latest_term_average"],
        "term_number": context["terms_monitored"],
    }
    return "ADVISOR_SIGNOFF"


def advisor_signoff(context: dict) -> str:
    # --- HITL ---
    # Condition (written policy, not the agent's judgement call): the agent
    # may never change a student's official intervention plan, and may never
    # recommend dismissal, without an advisor's sign-off.
    ev = context["_last_eval"]
    out_of_terms = context["terms_monitored"] >= MAX_TERMS_MONITORED
    recommendation = "clear" if ev["improved"] else ("dismiss" if out_of_terms else "continue_monitoring")
    raise HITLRequired(
        reason="advisor sign-off required before changing a student's intervention plan status",
        payload={
            "student_id": context["student_id"],
            "term_number": ev["term_number"],
            "term_average": ev["average"],
            "agent_recommendation": recommendation,
        },
    )


def _on_advisor_decision(context: dict, decision: dict) -> str:
    context["history"].append({"event": "advisor_decision", "decision": decision})
    action = decision.get("action")
    if action == "clear":
        return "DONE_CLEARED"
    if action == "dismiss":
        return "DONE_DISMISSED"
    # action == "continue_monitoring" -> genuine cycle back to an
    # already-visited state, for the next term.
    context["term_grades_posted"] = False
    return "MONITOR_TERM"


def build_graph() -> StateGraph:
    nodes = {
        "INTAKE": Node("INTAKE", intake, techniques=[], why="plain DB read + threshold check"),
        "BUILD_INTERVENTION_PLAN": Node(
            "BUILD_INTERVENTION_PLAN", build_intervention_plan,
            techniques=["task_decomposition"],
            why="the plan's shape (which steps, in what order) depends on why this "
                "specific student is at risk, not just on a fixed template",
        ),
        "FETCH_POLICY": Node(
            "FETCH_POLICY", fetch_policy,
            techniques=["rag"],
            why="the concrete probation thresholds live in unstructured policy text, "
                "not in a table this agent can query directly",
        ),
        "MONITOR_TERM": Node(
            "MONITOR_TERM", monitor_term, on_external_event=_on_term_grades_posted,
            why="waits on instructors posting grades over the term — an external actor",
        ),
        "EVALUATE_TERM": Node("EVALUATE_TERM", evaluate_term),
        "ADVISOR_SIGNOFF": Node(
            "ADVISOR_SIGNOFF", advisor_signoff, on_hitl_resolved=_on_advisor_decision,
            why="changing a student's official standing is never the agent's call alone",
        ),
    }
    return StateGraph(
        name="probation_monitoring",
        nodes=nodes,
        start_state="INTAKE",
        terminal_states={"DONE_NOT_ELIGIBLE", "DONE_CLEARED", "DONE_DISMISSED"},
    )
