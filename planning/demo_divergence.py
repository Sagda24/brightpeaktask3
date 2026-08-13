import json
import os
import shutil
import tempfile

import planning.db_tools as db_tools
from planning.dag import DAGCycleError
from planning.decomposition import decompose_first, execute_dag
from planning.dynamic_decomposition import dynamic_decompose_and_execute
from planning.llm_client import MockLLM


ORIGINAL_DB_PATH = db_tools.DB_PATH


def _fresh_scratch_db() -> str:
    """This demo calls the real enroll tool, which really writes rows.
    Point db_tools at a fresh throwaway copy of brightpeak.db, always
    copied from the untouched original, so (a) the two methods both
    start from Kareem Reda's real recorded transcript, (b) neither run
    contaminates the other's starting state, and (c) nothing is ever
    permanently written to the actual academy database by this demo."""
    scratch = os.path.join(tempfile.mkdtemp(prefix="brightpeak_demo_"), "brightpeak.db")
    shutil.copy(ORIGINAL_DB_PATH, scratch)
    db_tools.DB_PATH = scratch
    return scratch


def main():
    print(f"(each method below runs against its own fresh scratch copy of the DB)\n")
    request = {
        "student_id": 7,
        "free_text": "Please register me for Software Engineering Principles (course_id 4) this semester.",
    }

    print("=" * 70)
    print("DECOMPOSITION-FIRST")
    print("=" * 70)
    _fresh_scratch_db()
    llm1 = MockLLM()
    dag1 = decompose_first(request, llm1)
    dag1 = execute_dag(dag1)
    for tid in dag1.topological_order():
        n = dag1.nodes[tid]
        print(f"  [{n.status:7s}] {n.task_id:6s} {n.tool:20s} -> {json.dumps(n.result)}")
    print(f"  LLM calls: {dag1.llm_calls}   total tokens: {dag1.total_tokens}")
    trace1 = dag1.save_trace("artifacts")
    print(f"  trace saved: {trace1}")

    enroll_node = dag1.nodes.get("t3")
    if enroll_node and enroll_node.result.get("status") == "success":
        print(
            "  !! decomposition-first ENROLLED an ineligible student "
            "(enroll_student does not itself check prerequisites) — "
            "this is the real cost-of-a-wrong-plan case."
        )

    print()
    print("=" * 70)
    print("DYNAMIC DECOMPOSITION")
    print("=" * 70)
    _fresh_scratch_db()
    llm2 = MockLLM()
    dag2 = dynamic_decompose_and_execute(request, llm2)
    for tid in dag2.topological_order():
        n = dag2.nodes[tid]
        print(f"  [{n.status:7s}] {n.task_id:6s} {n.tool:20s} -> {json.dumps(n.result)}")
    replans = [e for e in dag2.events if e["kind"] == "replan"]
    print(f"  LLM calls: {dag2.llm_calls}   total tokens: {dag2.total_tokens}   replans: {len(replans)}")
    for r in replans:
        print(f"    replan @ {r['task_id']}: {r['reason']}")
    trace2 = dag2.save_trace("artifacts")
    print(f"  trace saved: {trace2}")

    print()
    print("=" * 70)
    print("DIVERGENCE SUMMARY")
    print("=" * 70)
    print(
        "  decomposition-first: fixed 3-step plan generated once; still "
        "executed the course-4 enrollment step after check_prerequisites "
        "reported ineligible, because the plan never re-consulted the "
        "model after t2's result."
    )
    print(
        "  dynamic decomposition: after observing check_prerequisites "
        "come back ineligible, generated a NEW next step targeting the "
        "missing prerequisite instead of proceeding to the originally "
        "requested enrollment."
    )
    print(
        f"  cost: decomposition-first used {dag1.llm_calls} LLM call(s) / "
        f"{dag1.total_tokens} tokens; dynamic used {dag2.llm_calls} call(s) / "
        f"{dag2.total_tokens} tokens for the correct outcome."
    )

    # Acyclicity guardrail demo: constructing a deliberately cyclic plan
    # must fail at construction time, not execution time.
    print()
    print("=" * 70)
    print("CYCLE ENFORCEMENT CHECK")
    print("=" * 70)
    from planning.dag import DAG, Node
    bad = DAG(request=request, method="decomposition_first")
    bad.add_node(Node(task_id="a", instruction="x", tool="get_profile", depends_on=[]))
    bad.add_node(Node(task_id="b", instruction="y", tool="get_profile", depends_on=["a"]))
    try:
        # force a's deps to include b -> cycle a->b->a
        bad.nodes["a"].depends_on.append("b")
        bad.topological_order()
        print("  !! FAILED to detect a cycle")
    except DAGCycleError as e:
        print(f"  correctly rejected a cyclic plan: {e}")


if __name__ == "__main__":
    main()
