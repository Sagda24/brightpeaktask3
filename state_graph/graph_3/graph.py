"""
Graph 3 — Certificate Issuance with Compliance Hold Resolution

WHY THIS NEEDS A STATE GRAPH:
- Real branch outside the model's control: eligibility depends on financial,
  disciplinary, and prerequisite holds set by other offices, not by the
  agent — and a hold can be waived mid-run by a person who isn't the agent.
- Real failure a single retry can't fix: an enrollment/credits record that's
  missing or inconsistent mid-check isn't something re-running the same
  check fixes; it needs a person to look at the data.
- Real human decision, and a genuinely irreversible action: issuing a signed
  certificate cannot be un-sent once issued. The agent may never waive a
  compliance hold on its own, and may never take the issuance action itself
  without a registrar's sign-off, no matter how clean the checks look.

TWO LLM-CALL TECHNIQUES USED, AND WHY:
- LATS (RUN_ELIGIBILITY_CHECKS): eligibility is a search over which checks
  to run and in what order, scored against a real, defensible eligibility
  rubric (credits complete, no financial hold, no disciplinary hold,
  prerequisites complete) — not the model's own opinion of what "looks
  eligible." LATS is the right fit because it searches multiple candidate
  check orderings and scores them against that rubric, rather than a single
  fixed pass.
- Constrained ReAct (ATTEMPT_AUTO_RESOLVE, ISSUE_CERTIFICATE): both nodes
  may only call a fixed whitelist of actions (re-check a payment status,
  write the final certificate record) — never an arbitrary DB write, and
  never the issuance action without having gone through HITL_FINAL_SIGNOFF
  first.
"""

import sqlite3
import time

from state_graph.engine import HITLRequired, Node, StateGraph
from state_graph.checkpointing.store import DB_PATH

CHECKS = ["credits_complete", "financial_hold", "disciplinary_hold", "prerequisite_complete"]
MAX_AUTO_RESOLVE_ATTEMPTS = 2


def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------
# Constrained ReAct whitelist
# ---------------------------------------------------------------------

def _act_recheck_financial_hold(args: dict) -> dict:
    # Stand-in for a real "recheck_payment_status" MCP tool call. Only ever
    # invoked from ATTEMPT_AUTO_RESOLVE, never anywhere else in this graph.
    return {"status": "success", "hold_cleared": bool(args.get("simulate_payment_cleared", False))}


def _act_issue_certificate(args: dict) -> dict:
    conn = _db()
    try:
        row = conn.execute(
            "SELECT e.enrollment_id FROM enrollments e "
            "WHERE e.student_id = ? AND e.status = 'COMPLETED' "
            "AND e.enrollment_id NOT IN (SELECT enrollment_id FROM certificates) "
            "LIMIT 1",
            (args["student_id"],),
        ).fetchone()
        if not row:
            return {"status": "error", "message": "no completed, not-yet-certified enrollment on record"}
        code = f"CERT-{args['student_id']}-{int(time.time())}"
        conn.execute(
            "INSERT INTO certificates (enrollment_id, issue_date, certificate_code) VALUES (?, date('now'), ?)",
            (row["enrollment_id"], code),
        )
        conn.commit()
        return {"status": "success", "certificate_code": code}
    finally:
        conn.close()


WHITELISTED_ACTIONS = {
    "recheck_financial_hold": _act_recheck_financial_hold,
    "issue_certificate": _act_issue_certificate,
}


def _constrained_call(action: str, args: dict) -> dict:
    if action not in WHITELISTED_ACTIONS:
        raise Exception(f"constrained ReAct violation: '{action}' is not a whitelisted action")
    return WHITELISTED_ACTIONS[action](args)


# ---------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------

def request_received(context: dict) -> str:
    conn = _db()
    row = conn.execute("SELECT student_id FROM students WHERE student_id = ?", (context["student_id"],)).fetchone()
    conn.close()
    if not row:
        # A genuinely missing student record mid-flow is unplanned -> ticket,
        # not a policy branch this graph knows how to route around.
        raise Exception(f"student_id={context['student_id']} not found while opening certificate request")
    context.setdefault("history", []).append({"event": "request_received"})
    context.setdefault("auto_resolve_attempts", 0)
    return "RUN_ELIGIBILITY_CHECKS"


def run_eligibility_checks(context: dict) -> str:
    # --- LATS ---
    # Real LATS would search over several candidate orderings of CHECKS and
    # score each against the eligibility rubric below, picking the ordering
    # that surfaces the most severe blocking hold fastest. The scoring rubric
    # itself (holds[...]) is the real, defensible eligibility check — LATS
    # controls the SEARCH over how to apply it, not the rubric's outcome.
    holds = context.get("simulated_holds", {})  # e.g. {"financial_hold": True}
    candidate_orderings = [
        CHECKS,
        ["financial_hold", "disciplinary_hold", "credits_complete", "prerequisite_complete"],
    ]

    def score(ordering):
        # Reward orderings that reach a blocking hold in fewer steps.
        for i, check in enumerate(ordering):
            if holds.get(check):
                return -i  # higher (less negative) is better -> found it earlier
        return 1  # nothing blocking found -> fully explored, still a valid path

    best_ordering = max(candidate_orderings, key=score)
    context.setdefault("history", []).append(
        {"event": "eligibility_search", "orderings_considered": candidate_orderings, "chosen": best_ordering}
    )

    for check in best_ordering:
        if holds.get(check):
            context["blocking_check"] = check
            return "HOLD_FOUND"

    context["blocking_check"] = None
    return "HITL_FINAL_SIGNOFF"


def hold_found(context: dict) -> str:
    context.setdefault("history", []).append({"event": "hold_found", "check": context["blocking_check"]})
    if context["blocking_check"] == "financial_hold" and context["auto_resolve_attempts"] < MAX_AUTO_RESOLVE_ATTEMPTS:
        return "ATTEMPT_AUTO_RESOLVE"
    return "HITL_REGISTRAR_HOLD_REVIEW"


def attempt_auto_resolve(context: dict) -> str:
    # --- Constrained ReAct ---
    context["auto_resolve_attempts"] += 1
    result = _constrained_call(
        "recheck_financial_hold", {"simulate_payment_cleared": context.get("simulate_payment_cleared", False)}
    )
    context.setdefault("history", []).append({"event": "auto_resolve_attempted", "result": result})
    if result.get("hold_cleared"):
        context["simulated_holds"] = {**context.get("simulated_holds", {}), "financial_hold": False}
        # genuine cycle: re-run the full eligibility search now that a hold changed
        return "RUN_ELIGIBILITY_CHECKS"
    return "HOLD_FOUND"


def hitl_registrar_hold_review(context: dict) -> str:
    # --- HITL ---
    # Condition: the agent may never waive a compliance hold on its own.
    raise HITLRequired(
        reason=f"compliance hold '{context['blocking_check']}' cannot be waived by the agent",
        payload={"student_id": context["student_id"], "blocking_check": context["blocking_check"]},
    )


def _on_hold_review_decision(context: dict, decision: dict) -> str:
    context.setdefault("history", []).append({"event": "hold_review_decision", "decision": decision})
    if decision.get("action") == "waive":
        context["simulated_holds"] = {**context.get("simulated_holds", {}), context["blocking_check"]: False}
        return "RUN_ELIGIBILITY_CHECKS"  # genuine cycle: recheck everything
    return "DONE_DENIED"


def hitl_final_signoff(context: dict) -> str:
    # --- HITL ---
    # Condition: issuing a certificate is irreversible once sent — the agent
    # may never take that action without a registrar's sign-off, even when
    # every check came back clean.
    raise HITLRequired(
        reason="certificate issuance is irreversible and requires registrar sign-off, even with a clean check",
        payload={"student_id": context["student_id"]},
    )


def _on_final_signoff_decision(context: dict, decision: dict) -> str:
    context.setdefault("history", []).append({"event": "final_signoff_decision", "decision": decision})
    if decision.get("action") == "approve":
        return "ISSUE_CERTIFICATE"
    return "DONE_DENIED"


def issue_certificate(context: dict) -> str:
    # --- Constrained ReAct ---
    result = _constrained_call("issue_certificate", {"student_id": context["student_id"]})
    context.setdefault("history", []).append({"event": "certificate_issued", "result": result})
    if result["status"] != "success":
        raise Exception(f"issue_certificate failed: {result['message']}")
    context["certificate_code"] = result["certificate_code"]
    return "DONE_ISSUED"


def build_graph() -> StateGraph:
    nodes = {
        "REQUEST_RECEIVED": Node("REQUEST_RECEIVED", request_received),
        "RUN_ELIGIBILITY_CHECKS": Node(
            "RUN_ELIGIBILITY_CHECKS", run_eligibility_checks,
            techniques=["lats"],
            why="searches over check orderings scored against a real eligibility rubric",
        ),
        "HOLD_FOUND": Node("HOLD_FOUND", hold_found),
        "ATTEMPT_AUTO_RESOLVE": Node(
            "ATTEMPT_AUTO_RESOLVE", attempt_auto_resolve,
            techniques=["constrained_react"],
            why="only a whitelisted recheck_financial_hold action may run here",
        ),
        "HITL_REGISTRAR_HOLD_REVIEW": Node(
            "HITL_REGISTRAR_HOLD_REVIEW", hitl_registrar_hold_review, on_hitl_resolved=_on_hold_review_decision,
            why="a compliance hold can never be waived by the agent alone",
        ),
        "HITL_FINAL_SIGNOFF": Node(
            "HITL_FINAL_SIGNOFF", hitl_final_signoff, on_hitl_resolved=_on_final_signoff_decision,
            why="issuance is irreversible; always requires sign-off, holds or not",
        ),
        "ISSUE_CERTIFICATE": Node(
            "ISSUE_CERTIFICATE", issue_certificate,
            techniques=["constrained_react"],
            why="only a whitelisted issue_certificate action may run here, and only after HITL sign-off",
        ),
    }
    return StateGraph(
        name="certificate_issuance",
        nodes=nodes,
        start_state="REQUEST_RECEIVED",
        terminal_states={"DONE_ISSUED", "DONE_DENIED"},
    )
