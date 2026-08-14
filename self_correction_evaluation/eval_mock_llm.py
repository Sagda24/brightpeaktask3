"""
Deterministic, offline stand-in for the evaluation run below -- same role
as `self_correction.mock_llm.MockSelfCorrectionLLM`, generalized to any
`check_prerequisites` / `credit_load` task instead of one fixed scenario,
so the same mock can be pointed at every case in `test_cases.json`.

Modeling choice, and why it's a fair stand-in for a real model:
- FIRST GUESS is deliberately optimistic ("eligible: true" /
  "within_limit: true") with no grounding -- this mirrors a documented
  real failure mode of ungrounded LLM judges/generators on eligibility-style
  questions: an affirmative-sounding answer is the "safe-looking" default
  absent evidence to the contrary.
- On REFINE / a later REFLEXION attempt, the mock recomputes the real
  answer via the same `planning.db_tools` handlers this repo already
  uses as ground truth -- standing in for what a competent model would
  eventually produce once told concretely what it got wrong (the
  critique text already names the mistake; the mock just also gets it
  right, which is the whole conditional-improvement premise both
  Self-Refine and Reflexion depend on).
- The UNGROUNDED JUDGE always rubber-stamps whatever candidate it sees
  (no ground truth available to it) -- this is the exact mechanism being
  measured, not a shortcut around it.

To swap in a real model for this evaluation, replace
`GeneralMockLLM()` in evaluate_self_correction.py with
`planning.llm_client.AnthropicLLM()` (requires ANTHROPIC_API_KEY) --
nothing else in this file or in self_correction/ needs to change.
"""
from __future__ import annotations

import json
import re

from planning.llm_client import LLMResponse
from planning.db_tools import TOOL_REGISTRY


def _extract_tool_call(prompt: str):
    tool_m = re.search(r"TOOL:\s*(\w+)", prompt)
    args_m = re.search(r"TOOL ARGS:\s*(\{.*\})", prompt)
    if not tool_m or not args_m:
        return None, {}
    try:
        return tool_m.group(1), json.loads(args_m.group(1))
    except (ValueError, json.JSONDecodeError):
        return tool_m.group(1), {}


def _optimistic_guess(tool: str) -> dict:
    if tool == "check_prerequisites":
        return {"status": "success", "eligible": True, "missing_prereqs": []}
    if tool == "credit_load":
        return {"status": "success", "within_limit": True}
    return {"status": "success"}


def _grounded_guess(tool: str, tool_args: dict) -> dict:
    handler = TOOL_REGISTRY.get(tool)
    if handler is None:
        return {"status": "error", "message": f"no handler for {tool}"}
    try:
        return handler(**tool_args)
    except Exception as e:
        return {"status": "error", "message": str(e)}


class GeneralMockLLM:
    def __init__(self):
        self.calls = 0

    def call(self, prompt: str, *, max_tokens: int = 250) -> LLMResponse:
        self.calls += 1
        text = self._respond(prompt)
        return LLMResponse(text, len(prompt.split()), len(text.split()))

    def _respond(self, prompt: str) -> str:
        if "Return ONLY a JSON object: {\"passed\"" in prompt:
            # ungrounded judge: rubber-stamps, no ground truth available
            return json.dumps({"passed": True, "score": 0.85, "reason": "looks plausible"})
        if "explain what the candidate got wrong" in prompt:
            return "The candidate guessed optimistically instead of checking the real record."
        if "Write a SHORT (1-2 sentence) first-person verbal reflection" in prompt:
            return ("I guessed optimistically instead of verifying against the real record; "
                    "next time I should check the actual data before answering.")
        if "REFLECTIONS FROM YOUR PREVIOUS ATTEMPTS" in prompt:
            tool, args = _extract_tool_call(prompt)
            if "(none yet -- first attempt)" in prompt:
                return json.dumps(_optimistic_guess(tool))
            return json.dumps(_grounded_guess(tool, args))
        if "Produce an IMPROVED candidate result" in prompt:
            tool, args = _extract_tool_call(prompt)
            return json.dumps(_grounded_guess(tool, args))
        if "Produce your best-effort RESULT" in prompt:
            tool, _args = _extract_tool_call(prompt)
            return json.dumps(_optimistic_guess(tool))
        return json.dumps({"note": "mock: unrecognized prompt shape"})
