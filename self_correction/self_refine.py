"""
Self-Refine: generate -> critique -> refine, all within ONE episode.

Unlike Reflexion (reflexion.py), there is no persistent memory across
separate trials here -- the loop keeps revising the SAME candidate answer
in place using the immediately preceding critique, and stops as soon as
the environment's feedback says it's good enough (or a max-iteration
budget runs out). This matches the shape of the original Self-Refine
paper: one working draft, iteratively critiqued and rewritten.

The critique/pass-fail signal comes from whichever `Environment` is
injected (see environment.py) -- grounded or ungrounded -- so this file
contains no policy logic itself and stays reusable across both.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from self_correction.environment import Feedback


GENERATE_PROMPT = """You are solving one sub-task for the Brightpeak Academy
registration planner.

TASK: {instruction}
TOOL: {tool}
TOOL ARGS: {tool_args}

Produce your best-effort RESULT for this task as a JSON object (same shape
you'd expect the real tool to return, e.g. for check_prerequisites:
{{"status": "success", "eligible": bool, "missing_prereqs": [...]}}).
Return ONLY the JSON object.
"""

REFINE_PROMPT = """You previously produced this candidate result for a
Brightpeak Academy registration sub-task, and it was reviewed.

TASK: {instruction}
TOOL: {tool}
TOOL ARGS: {tool_args}

PREVIOUS CANDIDATE:
{candidate}

REVIEW FEEDBACK (why it did not pass):
{reason}

Produce an IMPROVED candidate result as a JSON object that addresses the
feedback. Return ONLY the JSON object.
"""


@dataclass
class RefineStep:
    iteration: int
    candidate: dict
    feedback: Feedback


@dataclass
class RefineResult:
    final_candidate: dict
    converged: bool           # True if feedback.passed before hitting max_iterations
    history: list = field(default_factory=list)   # list[RefineStep]
    llm_calls: int = 0
    total_tokens: int = 0

    @property
    def iterations(self) -> int:
        return len(self.history)


class SelfRefine:
    def __init__(self, llm, environment, max_iterations: int = 3, score_threshold: float = 0.8):
        self.llm = llm
        self.environment = environment
        self.max_iterations = max_iterations
        self.score_threshold = score_threshold

    def run(self, task: dict, initial_candidate: Optional[dict] = None) -> RefineResult:
        result = RefineResult(final_candidate={}, converged=False)

        candidate = initial_candidate or self._generate(task, result)
        for i in range(1, self.max_iterations + 1):
            feedback, judge_response = self.environment.evaluate(task, candidate)
            if judge_response is not None:
                result.llm_calls += 1
                result.total_tokens += judge_response.total_tokens
            result.history.append(RefineStep(iteration=i, candidate=candidate, feedback=feedback))

            if feedback.passed or feedback.score >= self.score_threshold:
                result.final_candidate = candidate
                result.converged = True
                return result

            if i == self.max_iterations:
                break  # budget exhausted; fall through, return last candidate as-is

            candidate = self._refine(task, candidate, feedback, result)

        result.final_candidate = candidate
        return result

    def _generate(self, task: dict, result: RefineResult) -> dict:
        prompt = GENERATE_PROMPT.format(
            instruction=task.get("instruction", ""),
            tool=task.get("tool", ""),
            tool_args=json.dumps(task.get("tool_args", {})),
        )
        response = self.llm.call(prompt, max_tokens=250)
        result.llm_calls += 1
        result.total_tokens += response.total_tokens
        return _parse_json(response.text)

    def _refine(self, task: dict, candidate: dict, feedback: Feedback, result: RefineResult) -> dict:
        prompt = REFINE_PROMPT.format(
            instruction=task.get("instruction", ""),
            tool=task.get("tool", ""),
            tool_args=json.dumps(task.get("tool_args", {})),
            candidate=json.dumps(candidate),
            reason=feedback.reason,
        )
        response = self.llm.call(prompt, max_tokens=250)
        result.llm_calls += 1
        result.total_tokens += response.total_tokens
        return _parse_json(response.text)


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if "\n" in text else text
    try:
        return json.loads(text)
    except (ValueError, json.JSONDecodeError):
        return {"status": "error", "message": f"unparsable candidate: {text[:120]}"}
