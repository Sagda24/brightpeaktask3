"""
Deterministic, offline stand-in for the self-correction loop -- same
purpose as `planning.llm_client.MockLLM`: exercise self_refine.py,
reflexion.py, environment.py, and integration.py without network/API
access. Not what the system ships with; used only by
test_self_correction.py and demo_grounded_vs_ungrounded.py.

The scripted behavior deliberately reproduces a realistic failure mode:
first guess at an eligibility check is a plausible-sounding but WRONG
"eligible: true", an ungrounded judge rubber-stamps its own guess, and
only grounded feedback (the real tool_check_prerequisites result) forces
a correction -- after which the mock "learns" and gets it right, the way
a real model conditioned on a concrete critique/reflection would.
"""
from __future__ import annotations

import json

from planning.llm_client import LLMResponse


class MockSelfCorrectionLLM:
    def __init__(self):
        self.calls = 0

    def call(self, prompt: str, *, max_tokens: int = 250) -> LLMResponse:
        self.calls += 1
        text = self._respond(prompt)
        return LLMResponse(text, len(prompt.split()), len(text.split()))

    def _respond(self, prompt: str) -> str:
        if "Return ONLY a JSON object: {\"passed\"" in prompt:
            return self._ungrounded_judge(prompt)
        if "explain what the candidate got wrong" in prompt:
            return "The candidate assumed eligibility without checking the actual completed/failed course history."
        if "Write a SHORT (1-2 sentence) first-person verbal reflection" in prompt:
            return ("I assumed eligibility instead of checking the transcript; next time I should "
                    "explicitly verify each prerequisite against completed courses before answering.")
        if "REFLECTIONS FROM YOUR PREVIOUS ATTEMPTS" in prompt:
            return self._attempt(prompt)
        if "Produce an IMPROVED candidate result" in prompt:
            return self._improved_candidate(prompt)
        if "Produce your best-effort RESULT" in prompt:
            return self._first_guess(prompt)
        return json.dumps({"note": "mock: unrecognized prompt shape"})

    # -- canned behavior -------------------------------------------------
    @staticmethod
    def _first_guess(prompt: str) -> str:
        # Plausible-sounding but wrong: guesses eligible without grounding.
        return json.dumps({"status": "success", "eligible": True, "missing_prereqs": []})

    @staticmethod
    def _improved_candidate(prompt: str) -> str:
        # Self-Refine: conditioned directly on the immediately preceding
        # critique text in THIS prompt.
        return json.dumps({"status": "success", "eligible": False, "missing_prereqs": [1]})

    @staticmethod
    def _attempt(prompt: str) -> str:
        # Reflexion: a fresh attempt, but conditioned on whether any prior
        # reflection is present in the prompt.
        if "(none yet -- first attempt)" in prompt:
            return json.dumps({"status": "success", "eligible": True, "missing_prereqs": []})
        return json.dumps({"status": "success", "eligible": False, "missing_prereqs": [1]})

    @staticmethod
    def _ungrounded_judge(prompt: str) -> str:
        # The failure mode being demonstrated: an ungrounded judge has no
        # way to catch the wrong "eligible: true" guess, so it passes it.
        return json.dumps({"passed": True, "score": 0.9, "reason": "looks internally consistent"})
