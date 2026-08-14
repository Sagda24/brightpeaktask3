import pytest

from self_correction.environment import Environment, GroundedEnvironment
from self_correction.self_refine import SelfRefine
from self_correction.reflexion import Reflexion, ReflexionMemory
from self_correction.mock_llm import MockSelfCorrectionLLM
from self_correction.integration import execute_node
from planning.dag import DAG, Node

# Student 7 (Kareem Reda) has a DROPPED/45.0 attempt at course 1, which is
# below PASS_THRESHOLD -- so is genuinely ineligible for course 4, which
# requires passing course 1. Same fixture demo_divergence.py already uses.
TASK = {
    "task_id": "t2",
    "instruction": "check prerequisites for course 4",
    "tool": "check_prerequisites",
    "tool_args": {"student_id": 7, "course_id": 4},
}


def test_ungrounded_environment_rubber_stamps_wrong_guess():
    """The failure mode this whole module exists to demonstrate: an
    ungrounded judge has no ground truth to check against, so it passes
    a plausible-sounding but factually wrong first guess."""
    llm = MockSelfCorrectionLLM()
    env = Environment(llm)
    wrong_candidate = {"status": "success", "eligible": True, "missing_prereqs": []}
    feedback, _ = env.evaluate(TASK, wrong_candidate)
    assert feedback.passed is True
    assert feedback.grounded is False


def test_grounded_environment_catches_wrong_guess():
    llm = MockSelfCorrectionLLM()
    env = GroundedEnvironment(llm)
    wrong_candidate = {"status": "success", "eligible": True, "missing_prereqs": []}
    feedback, _ = env.evaluate(TASK, wrong_candidate)
    assert feedback.passed is False
    assert feedback.grounded is True
    assert feedback.evidence["eligible"] is False


def test_grounded_environment_confirms_correct_guess():
    llm = MockSelfCorrectionLLM()
    env = GroundedEnvironment(llm)
    correct_candidate = {"status": "success", "eligible": False, "missing_prereqs": [1]}
    feedback, _ = env.evaluate(TASK, correct_candidate)
    assert feedback.passed is True


def test_self_refine_converges_under_grounded_feedback():
    llm = MockSelfCorrectionLLM()
    result = SelfRefine(llm, GroundedEnvironment(llm), max_iterations=3).run(TASK)
    assert result.converged is True
    assert result.final_candidate["eligible"] is False
    # first guess wrong, refine step fixes it -> 2 iterations
    assert result.iterations == 2


def test_self_refine_never_converges_under_ungrounded_feedback():
    """With no ground truth, the ungrounded judge passes the FIRST
    (wrong) guess immediately -- 'converged' but on the wrong answer.
    This is exactly the comparison self_correction_evaluation/ measures."""
    llm = MockSelfCorrectionLLM()
    result = SelfRefine(llm, Environment(llm), max_iterations=3).run(TASK)
    assert result.converged is True
    assert result.iterations == 1
    assert result.final_candidate["eligible"] is True  # wrong, but "passed"


def test_reflexion_learns_across_trials_under_grounded_feedback():
    llm = MockSelfCorrectionLLM()
    memory = ReflexionMemory()
    result = Reflexion(llm, GroundedEnvironment(llm), memory=memory, max_trials=3).run(
        TASK, task_key="check_prerequisites"
    )
    assert result.success is True
    assert len(result.trials) == 2
    assert result.trials[0].reflection is not None
    # the reflection produced on trial 1 must be visible in memory before trial 2 ran
    assert memory.get("check_prerequisites") == [result.trials[0].reflection]


def test_integration_execute_node_grounded_vs_ungrounded():
    llm = MockSelfCorrectionLLM()
    dag = DAG(request={"student_id": 7, "free_text": "test"}, method="self_correction_demo")
    node = Node(
        task_id="t2", instruction="check prerequisites for course 4",
        tool="check_prerequisites", tool_args={"student_id": 7, "course_id": 4},
        suggested_method="SelfRefine",
    )
    dag.add_node(node)

    grounded_result = execute_node(node, dag, llm, grounded=True)
    assert grounded_result["eligible"] is False
    assert node.status == "done"
    assert dag.events[-1]["kind"] == "self_refine"
    assert dag.events[-1]["grounded"] is True
