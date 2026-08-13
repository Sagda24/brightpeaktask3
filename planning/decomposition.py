import json

from planning.dag import DAG, Node
from planning.db_tools import TOOL_REGISTRY

DECOMPOSE_PROMPT = """DECOMPOSE THE FULL REQUEST into a JSON list of sub-tasks
for the Brightpeak Academy registration planner, to be executed in
dependency order with NO further planning once execution starts.

Available tools (use one per sub-task, tool_args must match): 
- get_profile() -> student's completed/enrolled courses and grades
- check_prerequisites(course_id) -> grounded PRE-001/GRD-001/RET-001 check
- credit_load(additional_course_ids) -> semester overload check
- enroll(course_id) -> writes the enrollment (irreversible-ish; only call
  after eligibility is confirmed)
- search_policy(query) -> retrieves the relevant written policy text

Request:
student_id={student_id}
free_text="{free_text}"

Return ONLY a JSON array of objects with keys:
task_id, instruction, tool, tool_args, depends_on, suggested_method
(suggested_method is "PS" for a deterministic check/compute step,
"ToT" for a step with several valid orderings to weigh, "LATS" for
the final external-facing action that should be validated against
real feedback before it ships, or null).
"""


def build_decompose_prompt(student_id: int, free_text: str) -> str:
    return DECOMPOSE_PROMPT.format(student_id=student_id, free_text=free_text)


def parse_plan_json(text: str) -> list:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if "\n" in text else text
    return json.loads(text)


def decompose_first(request: dict, llm) -> DAG:
    """
    request: {"student_id": int, "free_text": str}
    llm: object with .call(prompt) -> LLMResponse (see llm_client.py)

    Single up-front LLM call generates the ENTIRE plan. Acyclicity is
    enforced as each node is added (DAG.add_node); a plan the model
    proposes that would deadlock is rejected here, before a single
    tool runs.
    """
    dag = DAG(request=request, method="decomposition_first")

    prompt = build_decompose_prompt(request["student_id"], request.get("free_text", ""))
    response = llm.call(prompt, max_tokens=600)
    dag.llm_calls += 1
    dag.total_tokens += response.total_tokens
    dag.log_event("plan_generated", raw=response.text)

    plan = parse_plan_json(response.text)
    for item in plan:
        args = dict(item.get("tool_args", {}))
        args.setdefault("student_id", request["student_id"])
        dag.add_node(
            Node(
                task_id=item["task_id"],
                instruction=item["instruction"],
                tool=item["tool"],
                tool_args=args,
                depends_on=item.get("depends_on", []),
                suggested_method=item.get("suggested_method"),
            )
        )
    return dag


def execute_dag(dag: DAG) -> DAG:
    """
    Executes every node in topological order, exactly as planned.
    This is the defining behavior under test: decomposition-first does
    NOT look at a node's result before deciding whether the next node
    still makes sense — it just runs the next node in the fixed order.
    If node t2 (check_prerequisites) comes back ineligible, node t3
    (enroll) still fires next, because the plan said so.
    """
    for task_id in dag.topological_order():
        node = dag.nodes[task_id]
        node.status = "running"
        handler = TOOL_REGISTRY[node.tool]
        try:
            node.result = handler(**node.tool_args)
            node.status = "done"
        except Exception as e:
            node.result = {"status": "error", "message": str(e)}
            node.status = "failed"
        dag.log_event("node_executed", task_id=task_id, status=node.status, result=node.result)
    return dag
