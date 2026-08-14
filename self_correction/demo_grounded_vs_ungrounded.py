"""
Same pedagogical shape as planning/demo_divergence.py, one level down: same
student (student_id=7, Kareem Reda -- DROPPED/45.0 at Introduction to
Computer Science, below the 60.0 pass threshold), same target course
(Software Engineering Principles, course_id=4, which requires passing
course 1), but this time holding the SUB-TASK fixed
(check_prerequisites) and varying which Environment judges the
self-correction loop: ungrounded (LLM opinion) vs grounded (real
tool_check_prerequisites).

Run it:
    python -m self_correction.demo_grounded_vs_ungrounded
"""
from self_correction.environment import Environment, GroundedEnvironment
from self_correction.self_refine import SelfRefine
from self_correction.mock_llm import MockSelfCorrectionLLM

TASK = {
    "task_id": "t2",
    "instruction": "check prerequisites for course 4",
    "tool": "check_prerequisites",
    "tool_args": {"student_id": 7, "course_id": 4},
}


def run(grounded: bool):
    llm = MockSelfCorrectionLLM()
    env = GroundedEnvironment(llm) if grounded else Environment(llm)
    result = SelfRefine(llm, env, max_iterations=3).run(TASK)
    label = "GROUNDED" if grounded else "UNGROUNDED"
    print(f"\n--- {label} ---")
    for step in result.history:
        print(f"  iter {step.iteration}: candidate={step.candidate} "
              f"-> passed={step.feedback.passed} score={step.feedback.score} "
              f"reason={step.feedback.reason!r}")
    print(f"  final: {result.final_candidate}  "
          f"(converged={result.converged}, iterations={result.iterations}, "
          f"llm_calls={result.llm_calls}, tokens={result.total_tokens})")
    return result


if __name__ == "__main__":
    ungrounded = run(grounded=False)
    grounded = run(grounded=True)

    print("\n=== Divergence ===")
    print(f"Ungrounded: converged in {ungrounded.iterations} iteration(s), "
          f"final eligible={ungrounded.final_candidate.get('eligible')} "
          f"({'WRONG' if ungrounded.final_candidate.get('eligible') else 'correct'}) "
          f"-- the judge rubber-stamped the first guess, no ground truth was ever checked.")
    print(f"Grounded:   converged in {grounded.iterations} iteration(s), "
          f"final eligible={grounded.final_candidate.get('eligible')} "
          f"({'correct' if not grounded.final_candidate.get('eligible') else 'WRONG'}) "
          f"-- caught against the real transcript, forced a correction.")
    print(f"Grounded cost ~{grounded.llm_calls / ungrounded.llm_calls:.1f}x the LLM calls "
          f"of ungrounded here -- the real trade-off: ungrounded is cheap and fine when "
          f"the first guess happens to be right, grounded earns its extra cost specifically "
          f"when being wrong has a real cost (writing a bad enrollment).")
