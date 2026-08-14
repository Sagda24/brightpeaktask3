"""
Environment feedback for the self-correction layer (Self-Refine / Reflexion).

Both algorithms need to answer the same question after a candidate
action/answer is produced: is it actually right, and if not, why?
There are two fundamentally different ways to answer that, and the whole
point of this module is to make the difference between them a first-class,
swappable thing rather than something buried inside a prompt:

- Environment (UNGROUNDED, the default): the critique comes from the LLM's
  own opinion of its own output. Nothing external is checked. This is
  cheap and requires no tool access, but it means the same model that made
  the mistake is also the one grading it -- a model that is confidently
  wrong about a student's eligibility will just as confidently approve its
  own wrong answer.

- GroundedEnvironment: the critique is checked against the REAL data this
  repo already has -- the same `planning.db_tools` handlers
  (`tool_check_prerequisites`, `tool_credit_load`, `tool_search_policy`, ...)
  that `dynamic_decomposition.py` calls against the live student record and
  the academy's own policies. No LLM opinion is involved in producing the
  ground truth; the LLM is only used to phrase the resulting reason.

`self_refine.py` and `reflexion.py` only depend on the shared `evaluate()`
interface below, so either environment can be dropped in without changing
the correction loop itself -- which is exactly what lets
`self_correction_evaluation/` run the same tasks through both and produce a
real grounded-vs-ungrounded comparison, the way `planning/README.md`
describes for decomposition-first vs dynamic decomposition.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from planning.db_tools import TOOL_REGISTRY


@dataclass
class Feedback:
    passed: bool
    score: float                    # 0.0-1.0
    reason: str
    grounded: bool
    evidence: Optional[dict] = field(default=None)  # real tool output, if any


class Environment:
    """Ungrounded (LLM-opinion-only) feedback. This is the toolkit's
    default -- cheap, no tool access required, but not checked against
    reality. Any candidate that "sounds right" can pass."""

    name = "ungrounded"

    CRITIQUE_PROMPT = """You are reviewing a candidate result for a Brightpeak
Academy registration task. Judge ONLY from the text below -- you do not have
access to the real database.

TASK: {instruction}
TOOL: {tool}({tool_args})

CANDIDATE RESULT:
{candidate}

Return ONLY a JSON object: {{"passed": bool, "score": float 0-1,
"reason": "one sentence"}}
"""

    def __init__(self, llm):
        self.llm = llm

    def evaluate(self, task: dict, candidate: dict) -> Feedback:
        prompt = self.CRITIQUE_PROMPT.format(
            instruction=task.get("instruction", ""),
            tool=task.get("tool", ""),
            tool_args=json.dumps(task.get("tool_args", {})),
            candidate=json.dumps(candidate),
        )
        response = self._call(prompt)
        parsed = self._parse(response.text)
        return Feedback(
            passed=bool(parsed.get("passed", False)),
            score=float(parsed.get("score", 0.0)),
            reason=parsed.get("reason", ""),
            grounded=False,
        ), response

    def _call(self, prompt: str):
        return self.llm.call(prompt, max_tokens=200)

    @staticmethod
    def _parse(text: str) -> dict:
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text.split("\n", 1)[1] if "\n" in text else text
        try:
            return json.loads(text)
        except (ValueError, json.JSONDecodeError):
            # Ungrounded judges can also fail to follow the format; treat
            # an unparsable critique as a fail-open non-pass rather than
            # crashing the correction loop.
            return {"passed": False, "score": 0.0, "reason": f"unparsable critique: {text[:120]}"}


class GroundedEnvironment(Environment):
    """Grounded feedback: re-derives the real answer via the actual tool
    (real DB / policy lookup, same TOOL_REGISTRY dynamic_decomposition.py
    uses) and compares the candidate against it. The LLM is only used to
    turn the comparison into a one-sentence reason -- never to decide
    pass/fail itself."""

    name = "grounded"

    REASON_PROMPT = """The candidate result for this task did not match the real,
ground-truth result. In one sentence, explain what the candidate got wrong.

TASK: {instruction}
CANDIDATE: {candidate}
GROUND TRUTH: {ground_truth}
"""

    @staticmethod
    def is_correct(task: dict, candidate: dict) -> bool:
        """Pure ground-truth check with NO LLM call involved -- used by
        evaluation code that needs to score a final candidate's actual
        correctness independently of which environment produced it
        (an ungrounded run can 'converge' while still being wrong)."""
        tool = task.get("tool")
        handler = TOOL_REGISTRY.get(tool)
        if handler is None:
            return False
        try:
            ground_truth = handler(**task.get("tool_args", {}))
        except Exception:
            return False
        passed, _score = GroundedEnvironment._compare(task, candidate, ground_truth)
        return passed

    def evaluate(self, task: dict, candidate: dict):
        tool = task.get("tool")
        handler = TOOL_REGISTRY.get(tool)
        if handler is None:
            # No grounded source for this tool -- fall back to the
            # ungrounded judge rather than fabricating a ground truth.
            return super().evaluate(task, candidate)

        try:
            ground_truth = handler(**task.get("tool_args", {}))
        except Exception as e:
            ground_truth = {"status": "error", "message": str(e)}

        passed, score = self._compare(task, candidate, ground_truth)
        if passed:
            return Feedback(
                passed=True, score=1.0, reason="matches grounded tool result",
                grounded=True, evidence=ground_truth,
            ), None

        response = self._call(
            self.REASON_PROMPT.format(
                instruction=task.get("instruction", ""),
                candidate=json.dumps(candidate),
                ground_truth=json.dumps(ground_truth),
            )
        )
        reason = response.text.strip()
        return Feedback(
            passed=False, score=score, reason=reason,
            grounded=True, evidence=ground_truth,
        ), response

    @staticmethod
    def _compare(task: dict, candidate: dict, ground_truth: dict) -> tuple:
        """Task-aware comparison against the grounded result. Falls back to
        a generic key-overlap score for tools not special-cased below."""
        tool = task.get("tool")

        if tool == "check_prerequisites":
            gt_eligible = ground_truth.get("eligible")
            cand_eligible = candidate.get("eligible")
            passed = gt_eligible is not None and gt_eligible == cand_eligible
            return passed, (1.0 if passed else 0.0)

        if tool == "enroll":
            # A candidate that decided to enroll is only correct if the
            # student was actually eligible; a candidate that refused to
            # enroll is only correct if the student was actually ineligible.
            gt_ok = ground_truth.get("status") == "success"
            cand_enrolled = candidate.get("status") == "success" or candidate.get("action") == "enroll"
            passed = gt_ok == cand_enrolled
            return passed, (1.0 if passed else 0.0)

        if tool == "credit_load":
            gt_ok = ground_truth.get("within_limit")
            cand_ok = candidate.get("within_limit")
            passed = gt_ok is not None and gt_ok == cand_ok
            return passed, (1.0 if passed else 0.0)

        # generic fallback: fraction of ground-truth keys the candidate
        # reproduces with an identical value
        keys = set(ground_truth.keys()) or {"status"}
        matches = sum(1 for k in keys if candidate.get(k) == ground_truth.get(k))
        score = matches / len(keys)
        return score >= 0.999, score
