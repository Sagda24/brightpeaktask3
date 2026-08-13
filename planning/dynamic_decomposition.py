import json

from planning.dag import DAG, Node
from planning.db_tools import TOOL_REGISTRY

NEXT_STEP_PROMPT = """You are planning ONE step at a time for the Brightpeak
Academy registration planner. Given what has already run and its REAL
result, decide the NEXT SUB-TASK, or say the plan is done.

Available tools (tool_args must match):
- get_profile() -> student's completed/enrolled courses and grades
- check_prerequisites(course_id) -> grounded PRE-001/GRD-001/RET-001 check
- credit_load(additional_course_ids) -> semester overload check
- enroll(course_id) -> writes the enrollment (only after eligibility confirmed)
- search_policy(query) -> retrieves relevant written policy text

Request:
student_id={student_id}
free_text="{free_text}"

COMPLETED TASKS:
{history}

Return ONLY a JSON object with keys task_id, instruction, tool,
tool_args, depends_on, suggested_method, done
(set done=true and omit the other keys once the request is fully
and safely resolved).
"""


def build_next_step_prompt(student_id: int, free_text: str, history: list) -> str:
    history_text = "\n".join(
        f"- {h['task_id']} ({h['tool']}) -> {json.dumps(h['result'])}" for h in history
    ) or "(none yet)"
    return NEXT_STEP_PROMPT.format(
        student_id=student_id, free_text=free_text, history=history_text
    )


def parse_step_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if "\n" in text else text
    return json.loads(text)


def dynamic_decompose_and_execute(request: dict, llm, max_steps: int = 8) -> DAG:
    """
    request: {"student_id": int, "free_text": str}
    llm: object with .call(prompt) -> LLMResponse

    Interleaves generation and execution: generate ONE node -> execute
    it against the real tool -> feed the real result back -> generate
    the next node. A replan is visible in the trace as a node whose
    tool/task_id was not implied by the immediately preceding plan
    step (see dag.events, kind="replan").
    """
    dag = DAG(request=request, method="dynamic")
    history = []  # [{"task_id", "tool", "result"}]
    last_missing_prereq_seen = None

    for _ in range(max_steps):
        prompt = build_next_step_prompt(request["student_id"], request.get("free_text", ""), history)
        response = llm.call(prompt, max_tokens=300)
        dag.llm_calls += 1
        dag.total_tokens += response.total_tokens

        step = parse_step_json(response.text)
        if step.get("done"):
            dag.log_event("plan_complete", after_steps=len(history))
            break

        args = dict(step.get("tool_args", {}))
        args.setdefault("student_id", request["student_id"])
        node = Node(
            task_id=step["task_id"],
            instruction=step["instruction"],
            tool=step["tool"],
            tool_args=args,
            depends_on=step.get("depends_on", []),
            suggested_method=step.get("suggested_method"),
        )

        # Cycle/dependency enforcement, same code path as decomposition-first.
        dag.add_node(node)

        # detect + log a genuine course-of-action change: the model is
        # reacting to an ineligible prerequisite result observed in the
        # previous step, rather than the originally requested course.
        if last_missing_prereq_seen and node.tool == "check_prerequisites" and \
                node.tool_args.get("course_id") in last_missing_prereq_seen:
            dag.log_event(
                "replan",
                reason="previous check_prerequisites came back ineligible; "
                       "inserting prerequisite course into the plan instead of "
                       "proceeding to the originally requested enrollment",
                task_id=node.task_id,
            )

        node.status = "running"
        handler = TOOL_REGISTRY[node.tool]
        try:
            node.result = handler(**node.tool_args)
            node.status = "done"
        except Exception as e:
            node.result = {"status": "error", "message": str(e)}
            node.status = "failed"

        dag.log_event("node_executed", task_id=node.task_id, status=node.status, result=node.result)
        history.append({"task_id": node.task_id, "tool": node.tool, "result": node.result})

        if node.tool == "check_prerequisites" and node.result.get("eligible") is False:
            last_missing_prereq_seen = set(node.result.get("missing_prereqs", []))
        else:
            last_missing_prereq_seen = None

    return dag
