"""
Reflexion: trial -> evaluate -> verbal reflection -> retry, across
SEPARATE trials, with the reflections carried forward as explicit text
memory (verbal reinforcement learning) rather than any gradient update.

This is the deliberate contrast with self_refine.py:
- Self-Refine keeps ONE working candidate and rewrites it in place using
  the immediately preceding critique.
- Reflexion runs a fresh, independent attempt each trial, but hands the
  model a running list of its own past reflections ("last time you
  assumed eligibility without checking the retake policy -- check it
  explicitly this time") so lessons accumulate across attempts instead of
  only informing the very next rewrite.

`ReflexionMemory` is intentionally the same shape as a tiny episodic
store (see memory/episodic.py in this repo) -- a list of
{task_key, reflection} entries -- so it could be backed by that module's
`EpisodicMemory` instead in a later integration without changing this
file's interface.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

from self_correction.environment import Feedback
from self_correction.self_refine import _parse_json


ATTEMPT_PROMPT = """You are solving one sub-task for the Brightpeak Academy
registration planner.

TASK: {instruction}
TOOL: {tool}
TOOL ARGS: {tool_args}

REFLECTIONS FROM YOUR PREVIOUS ATTEMPTS AT THIS KIND OF TASK (learn from
these, do not repeat the same mistakes):
{reflections}

Produce your best-effort RESULT for this task as a JSON object. Return
ONLY the JSON object.
"""

REFLECT_PROMPT = """Your attempt at this task did not pass review.

TASK: {instruction}
YOUR ATTEMPT: {candidate}
WHY IT FAILED: {reason}

Write a SHORT (1-2 sentence) first-person verbal reflection on what went
wrong and what you should do differently next time you face a task like
this. Return plain text, no JSON.
"""


class ReflexionMemory:
    """Verbal memory of past reflections, keyed by task type (`task_key`,
    e.g. the tool name) so reflections generalize across trials/tasks of
    the same kind rather than being tied to one specific run."""

    def __init__(self):
        self.entries: list = []   # [{"task_key": str, "reflection": str}]

    def add(self, task_key: str, reflection: str) -> None:
        self.entries.append({"task_key": task_key, "reflection": reflection})

    def get(self, task_key: str) -> list:
        return [e["reflection"] for e in self.entries if e["task_key"] == task_key]

    def clear(self) -> None:
        self.entries.clear()


@dataclass
class Trial:
    attempt: int
    candidate: dict
    feedback: Feedback
    reflection: Optional[str] = None


@dataclass
class ReflexionResult:
    success: bool
    trials: list = field(default_factory=list)   # list[Trial]
    llm_calls: int = 0
    total_tokens: int = 0

    @property
    def final_candidate(self) -> dict:
        return self.trials[-1].candidate if self.trials else {}


class Reflexion:
    def __init__(self, llm, environment, memory: Optional[ReflexionMemory] = None,
                 max_trials: int = 3, score_threshold: float = 0.8):
        self.llm = llm
        self.environment = environment
        self.memory = memory or ReflexionMemory()
        self.max_trials = max_trials
        self.score_threshold = score_threshold

    def run(self, task: dict, task_key: Optional[str] = None) -> ReflexionResult:
        task_key = task_key or task.get("tool", "generic")
        result = ReflexionResult(success=False)

        for attempt in range(1, self.max_trials + 1):
            candidate = self._attempt(task, task_key, result)
            feedback, judge_response = self.environment.evaluate(task, candidate)
            if judge_response is not None:
                result.llm_calls += 1
                result.total_tokens += judge_response.total_tokens

            trial = Trial(attempt=attempt, candidate=candidate, feedback=feedback)
            result.trials.append(trial)

            if feedback.passed or feedback.score >= self.score_threshold:
                result.success = True
                return result

            if attempt == self.max_trials:
                break  # budget exhausted; last trial's candidate stands as the final answer

            trial.reflection = self._reflect(task, candidate, feedback, result)
            self.memory.add(task_key, trial.reflection)

        return result

    def _attempt(self, task: dict, task_key: str, result: ReflexionResult) -> dict:
        reflections = self.memory.get(task_key)
        reflections_text = "\n".join(f"- {r}" for r in reflections) or "(none yet -- first attempt)"
        prompt = ATTEMPT_PROMPT.format(
            instruction=task.get("instruction", ""),
            tool=task.get("tool", ""),
            tool_args=json.dumps(task.get("tool_args", {})),
            reflections=reflections_text,
        )
        response = self.llm.call(prompt, max_tokens=250)
        result.llm_calls += 1
        result.total_tokens += response.total_tokens
        return _parse_json(response.text)

    def _reflect(self, task: dict, candidate: dict, feedback: Feedback, result: ReflexionResult) -> str:
        prompt = REFLECT_PROMPT.format(
            instruction=task.get("instruction", ""),
            candidate=json.dumps(candidate),
            reason=feedback.reason,
        )
        response = self.llm.call(prompt, max_tokens=100)
        result.llm_calls += 1
        result.total_tokens += response.total_tokens
        return response.text.strip()
