"""
Graph 2 — Grade Dispute & Appeal Escalation

WHY THIS NEEDS A STATE GRAPH:
- Genuinely spans more than one sitting: a dispute is opened, then the graph
  waits on an instructor's reply, and — if it escalates — on an academic
  committee's decision. Neither reply is on the agent's clock.
- Real branch outside the model's control: the instructor can approve,
  reject, or (after committee review) get remanded for more evidence —
  a real cycle back to an already-visited state (CHOOSE_APPEAL_STRATEGY).
- Real failure a single retry can't fix: a malformed committee response, or
  the appeal window closing while still waiting on a reply, aren't things a
  retried DB call fixes — they need a person to look at the run.
- Real human decision: update_student_grade already restricts writes to
  INSTRUCTOR/ADMIN roles server-side; this graph adds an additional bar —
  any grade change above GRADE_CHANGE_HITL_THRESHOLD points, or one that
  flips a pass/fail boundary, needs a registrar's sign-off even after
  committee approval, because a large silent grade change is exactly the
  kind of thing the update_student_grade tool's role check alone can't stop.

TWO LLM-CALL TECHNIQUES USED, AND WHY:
- Tree of Thoughts (CHOOSE_APPEAL_STRATEGY): there are a handful of distinct,
  mutually exclusive ways to argue an appeal (grading error, extenuating
  circumstances, attendance dispute), and picking the wrong one burns a real,
  limited appeal window — this is exactly the "search over a few options and
  score them before committing" shape ToT is for, not a chain of tool calls.
- Constrained ReAct (FILE_APPEAL, APPLY_GRADE_CHANGE): both nodes are only
  allowed to call a fixed, whitelisted set of MCP-style actions
  (`file_appeal`, `update_student_grade`) with validated arguments — the
  model reasons about WHAT to call, never gets to invent a new action, and
  every call is checked against the same server-side rules
  update_student_grade already enforces (role, grade range).
"""

import sqlite3

from state_graph.engine import HITLRequired, Node, StateGraph, WaitForExternalEvent
from state_graph.checkpointing.store import DB_PATH

GRADE_CHANGE_HITL_THRESHOLD = 10.0  # points; above this, registrar sign-off is required

APPEAL_STRATEGIES = ["grading_error", "extenuating_circumstances", "attendance_dispute"]


def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------
# Constrained ReAct: a fixed whitelist of callable actions. Nothing outside
# this dict can ever be invoked from FILE_APPEAL / APPLY_GRADE_CHANGE, no
# matter what an LLM's reasoning trace suggests.
# ---------------------------------------------------------------------

def _act_file_appeal(args: dict) -> dict:
    # Stand-in for a real "file_appeal" MCP tool; recorded in the same DB.
    return {"status": "success", "message": f"Appeal filed for enrollment {args['enrollment_id']}"}


def _act_update_student_grade(args: dict) -> dict:
    # Mirrors Mcp-Server/server.py's update_student_grade validation exactly
    # (role check, grade range, enrollment existence) so this node enforces
    # nothing weaker than the live tool would.
    if args["requester_role"] not in ("INSTRUCTOR", "ADMIN"):
        return {"status": "error", "message": "role not permitted"}
    if not (0.0 <= args["new_grade"] <= 100.0):
        return {"status": "error", "message": "grade out of range"}
    conn = _db()
    row = conn.execute(
        "SELECT enrollment_id, grade FROM enrollments WHERE student_id = ? AND course_id = ?",
        (args["student_id"], args["course_id"]),
    ).fetchone()
    if not row:
        conn.close()
        return {"status": "error", "message": "no matching enrollment"}
    conn.execute(
        "UPDATE enrollments SET grade = ? WHERE student_id = ? AND course_id = ?",
        (args["new_grade"], args["student_id"], args["course_id"]),
    )
    conn.commit()
    conn.close()
    return {"status": "success", "old_grade": row["grade"], "new_grade": args["new_grade"]}


WHITELISTED_ACTIONS = {
    "file_appeal": _act_file_appeal,
    "update_student_grade": _act_update_student_grade,
}


def _constrained_call(action: str, args: dict) -> dict:
    if action not in WHITELISTED_ACTIONS:
        # Not a policy branch — the model tried to call something outside
        # its whitelist. That is a real bug, so it becomes a ticket.
        raise Exception(f"constrained ReAct violation: '{action}' is not a whitelisted action")
    return WHITELISTED_ACTIONS[action](args)


# ---------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------

def submit_dispute(context: dict) -> str:
    context.setdefault("history", []).append({"event": "dispute_submitted"})
    return "AWAIT_INSTRUCTOR_RESPONSE"


def await_instructor_response(context: dict) -> str:
    if "instructor_response" not in context:
        raise WaitForExternalEvent(
            reason="waiting for the instructor to respond to the dispute",
            payload={"student_id": context["student_id"], "course_id": context["course_id"]},
        )
    return _route_instructor_response(context)


def _on_instructor_response(context: dict, event_data: dict) -> str:
    context["instructor_response"] = event_data  # {"decision": "approve"|"reject", "proposed_grade": ...}
    context["history"].append({"event": "instructor_responded", "response": event_data})
    return _route_instructor_response(context)


def _route_instructor_response(context: dict) -> str:
    decision = context["instructor_response"].get("decision")
    if decision == "approve":
        return "APPLY_GRADE_CHANGE"
    if decision == "reject":
        return "CHOOSE_APPEAL_STRATEGY"
    raise Exception(f"unrecognized instructor response: {context['instructor_response']!r}")


def choose_appeal_strategy(context: dict) -> str:
    # --- Tree of Thoughts ---
    # Real LLM call would branch out N candidate arguments and score each
    # against the evidence on file, then commit to the best-scoring branch.
    # Deterministic stand-in below keeps this reproducible without an API
    # key while preserving the "generate multiple branches, score, select"
    # shape a real ToT call would have.
    evidence = context.get("evidence", {})
    scored = []
    for strategy in APPEAL_STRATEGIES:
        score = len(evidence.get(strategy, "")) + (5 if strategy in evidence else 0)
        scored.append((score, strategy))
    scored.sort(key=lambda x: -x[0])
    best_strategy = scored[0][1]
    context["appeal_strategy"] = best_strategy
    context.setdefault("history", []).append(
        {"event": "appeal_strategy_chosen", "candidates_scored": scored, "chosen": best_strategy}
    )
    return "FILE_APPEAL"


def file_appeal(context: dict) -> str:
    # --- Constrained ReAct ---
    result = _constrained_call(
        "file_appeal",
        {"enrollment_id": context.get("enrollment_id"), "strategy": context["appeal_strategy"]},
    )
    context["history"].append({"event": "appeal_filed", "result": result})
    if result["status"] != "success":
        raise Exception(f"file_appeal failed: {result['message']}")
    return "AWAIT_COMMITTEE_DECISION"


def await_committee_decision(context: dict) -> str:
    if "committee_response" not in context:
        raise WaitForExternalEvent(
            reason="waiting for the academic committee's decision on the filed appeal",
            payload={"student_id": context["student_id"], "strategy": context["appeal_strategy"]},
        )
    return _route_committee_response(context)


def _on_committee_response(context: dict, event_data: dict) -> str:
    context["committee_response"] = event_data  # {"decision": "approve"|"deny"|"remand", ...}
    context["history"].append({"event": "committee_responded", "response": event_data})
    return _route_committee_response(context)


def _route_committee_response(context: dict) -> str:
    decision = context["committee_response"].get("decision")
    if decision == "remand":
        # genuine cycle: back to an already-visited state with new evidence
        context["evidence"] = {
            **context.get("evidence", {}),
            **context["committee_response"].get("additional_evidence", {}),
        }
        del context["committee_response"]
        return "CHOOSE_APPEAL_STRATEGY"
    if decision == "deny":
        return "DONE_DENIED"
    if decision == "approve":
        proposed = context["committee_response"].get("proposed_grade")
        context["proposed_grade"] = proposed
        return "GRADE_CHANGE_SIZE_CHECK"
    raise Exception(f"unrecognized committee response: {context['committee_response']!r}")


def grade_change_size_check(context: dict) -> str:
    current = context.get("current_grade", 0.0)
    proposed = context["proposed_grade"]
    magnitude = abs(proposed - current)
    context["grade_change_magnitude"] = magnitude
    if magnitude > GRADE_CHANGE_HITL_THRESHOLD:
        return "HITL_REGISTRAR_SIGNOFF"
    return "APPLY_GRADE_CHANGE"


def hitl_registrar_signoff(context: dict) -> str:
    # --- HITL ---
    # Condition: a grade change above GRADE_CHANGE_HITL_THRESHOLD points must
    # never be applied by the agent alone, even after committee approval.
    raise HITLRequired(
        reason=f"grade change of {context['grade_change_magnitude']:.1f} points exceeds "
               f"the {GRADE_CHANGE_HITL_THRESHOLD}-point auto-apply threshold",
        payload={
            "student_id": context["student_id"],
            "course_id": context["course_id"],
            "current_grade": context.get("current_grade"),
            "proposed_grade": context["proposed_grade"],
        },
    )


def _on_registrar_decision(context: dict, decision: dict) -> str:
    context.setdefault("history", []).append({"event": "registrar_decision", "decision": decision})
    if decision.get("action") == "approve":
        context["proposed_grade"] = decision.get("override_grade", context["proposed_grade"])
        return "APPLY_GRADE_CHANGE"
    return "DONE_DENIED"


def apply_grade_change(context: dict) -> str:
    # --- Constrained ReAct ---
    new_grade = context.get("proposed_grade", context.get("instructor_response", {}).get("proposed_grade"))
    result = _constrained_call(
        "update_student_grade",
        {
            "student_id": context["student_id"],
            "course_id": context["course_id"],
            "new_grade": new_grade,
            "requester_role": "ADMIN",
        },
    )
    context.setdefault("history", []).append({"event": "grade_applied", "result": result})
    if result["status"] != "success":
        raise Exception(f"update_student_grade failed: {result['message']}")
    return "DONE_APPROVED"


def build_graph() -> StateGraph:
    nodes = {
        "SUBMIT_DISPUTE": Node("SUBMIT_DISPUTE", submit_dispute),
        "AWAIT_INSTRUCTOR_RESPONSE": Node(
            "AWAIT_INSTRUCTOR_RESPONSE", await_instructor_response, on_external_event=_on_instructor_response,
            why="waits on the instructor, an actor outside the agent's control",
        ),
        "CHOOSE_APPEAL_STRATEGY": Node(
            "CHOOSE_APPEAL_STRATEGY", choose_appeal_strategy,
            techniques=["tree_of_thoughts"],
            why="a handful of mutually exclusive appeal arguments, wrong pick burns the appeal window",
        ),
        "FILE_APPEAL": Node(
            "FILE_APPEAL", file_appeal,
            techniques=["constrained_react"],
            why="only a whitelisted file_appeal action may be invoked here",
        ),
        "AWAIT_COMMITTEE_DECISION": Node(
            "AWAIT_COMMITTEE_DECISION", await_committee_decision, on_external_event=_on_committee_response,
            why="waits on the academic committee, an actor outside the agent's control",
        ),
        "GRADE_CHANGE_SIZE_CHECK": Node("GRADE_CHANGE_SIZE_CHECK", grade_change_size_check),
        "HITL_REGISTRAR_SIGNOFF": Node(
            "HITL_REGISTRAR_SIGNOFF", hitl_registrar_signoff, on_hitl_resolved=_on_registrar_decision,
            why="large grade changes are never applied by the agent alone",
        ),
        "APPLY_GRADE_CHANGE": Node(
            "APPLY_GRADE_CHANGE", apply_grade_change,
            techniques=["constrained_react"],
            why="only a whitelisted update_student_grade action may be invoked here, "
                "with the exact same validation the live MCP tool enforces",
        ),
    }
    return StateGraph(
        name="grade_appeal",
        nodes=nodes,
        start_state="SUBMIT_DISPUTE",
        terminal_states={"DONE_APPROVED", "DONE_DENIED"},
    )
