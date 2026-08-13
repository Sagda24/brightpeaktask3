from dataclasses import dataclass
import json
import os
import re


@dataclass
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class McpSamplingLLM:
    """Wraps fastmcp Context.sample(), the model-access path this repo
    already uses (see Mcp-Server/server.py: request_student_evaluation)."""

    def __init__(self, ctx):
        self.ctx = ctx

    async def call(self, prompt: str, *, max_tokens: int = 500) -> LLMResponse:
        response = await self.ctx.sample(messages=prompt, max_tokens=max_tokens)
        # fastmcp's sampling result doesn't expose token counts; approximate
        # from whitespace so cost/quality comparisons still have a number.
        approx_in = len(prompt.split())
        approx_out = len(response.text.split())
        return LLMResponse(response.text, approx_in, approx_out)


class AnthropicLLM:
    """Direct API path for offline batch evaluation (planning_eval/),
    where there is no live MCP client to sample through."""

    def __init__(self, model: str = "claude-sonnet-4-6"):
        import anthropic
        self.client = anthropic.Anthropic()
        self.model = model

    def call(self, prompt: str, *, max_tokens: int = 500) -> LLMResponse:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        return LLMResponse(text, resp.usage.input_tokens, resp.usage.output_tokens)


class MockLLM:
    """Deterministic offline stand-in, demo/tests only (see module
    docstring). Recognizes the registration-planning prompts this repo
    sends and returns a plausible structured plan so dag construction,
    cycle checks, and the decomposition-first vs dynamic divergence can
    be exercised without network access."""

    def __init__(self):
        self.calls = 0

    def call(self, prompt: str, *, max_tokens: int = 500) -> LLMResponse:
        self.calls += 1
        if "DECOMPOSE THE FULL REQUEST" in prompt:
            text = self._decompose_first_plan(prompt)
        elif "NEXT SUB-TASK" in prompt:
            text = self._next_step(prompt)
        else:
            text = json.dumps({"note": "mock: unrecognized prompt shape"})
        return LLMResponse(text, len(prompt.split()), len(text.split()))

    # -- canned behavior, mirrors what a real model would plausibly emit --
    def _decompose_first_plan(self, prompt: str) -> str:
        course_id = _extract_course_id(prompt)
        plan = [
            {"task_id": "t1", "instruction": "load student academic history",
             "tool": "get_profile", "tool_args": {}, "depends_on": []},
            {"task_id": "t2", "instruction": f"check prerequisites for course {course_id}",
             "tool": "check_prerequisites", "tool_args": {"course_id": course_id},
             "depends_on": ["t1"], "suggested_method": "PS"},
            {"task_id": "t3", "instruction": f"enroll student in course {course_id}",
             "tool": "enroll", "tool_args": {"course_id": course_id},
             "depends_on": ["t2"], "suggested_method": None},
        ]
        # Decomposition-first commits to this full plan up front and,
        # by construction, has no branch for "t2 comes back ineligible" —
        # that's the point being demonstrated.
        return json.dumps(plan)

    def _next_step(self, prompt: str) -> str:
        """Small explicit state machine over COMPLETED TASKS, mirroring
        what a real model would infer from the same history text:
        1) load the profile, 2) check prerequisites for the requested
        course, 3) if ineligible, check prerequisites for the FIRST
        missing course instead (reacting to the real result) and stop
        once that comes back eligible, 4) otherwise the plan is done."""
        course_id = _extract_course_id(prompt)
        completed_ids = set(re.findall(r'-\s*(\w+)\s*\(', prompt.split("COMPLETED TASKS:")[-1]))
        last_result = _last_result(prompt)

        if "t1" not in completed_ids:
            return json.dumps({"task_id": "t1", "instruction": "load student academic history",
                                "tool": "get_profile", "tool_args": {}, "depends_on": [], "done": False})

        if "t2" not in completed_ids:
            return json.dumps({"task_id": "t2", "instruction": f"check prerequisites for course {course_id}",
                                "tool": "check_prerequisites", "tool_args": {"course_id": course_id},
                                "depends_on": ["t1"], "suggested_method": "PS", "done": False})

        if last_result is not None and last_result.get("eligible") is False and "retake" not in completed_ids:
            missing = last_result.get("missing_prereqs", [1])[0]
            return json.dumps({
                "task_id": "retake",
                "instruction": f"react to ineligibility: check the missing prerequisite (course {missing}) "
                                f"instead of proceeding to the originally requested enrollment",
                "tool": "check_prerequisites",
                "tool_args": {"course_id": missing},
                "depends_on": ["t2"],
                "suggested_method": "PS",
                "done": False,
            })

        return json.dumps({"done": True})


def _extract_course_id(prompt: str) -> int:
    """Pulls the target course id out of the REQUEST section only
    (free_text="...") — never out of COMPLETED TASKS/history JSON,
    where student records also contain a "course_id" key and would
    otherwise be matched instead of the course the student asked about."""
    import re
    request_section = prompt.split("COMPLETED TASKS:")[0]
    m = re.search(r'free_text="[^"]*course[_ ]?id\s+(\d+)', request_section, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.search(r'free_text="[^"]*course\s+(\d+)', request_section, re.IGNORECASE)
    return int(m.group(1)) if m else 4


def _last_result(prompt: str) -> dict:
    """Parses the most recent '- task_id (tool) -> {json}' line out of
    the COMPLETED TASKS section, mirroring how a real model would read
    the last observed tool result back out of the prompt."""
    section = prompt.split("COMPLETED TASKS:")[-1]
    history = [line for line in section.splitlines() if line.strip().startswith("- ")]
    if not history:
        return None
    last_line = history[-1]
    try:
        return json.loads(last_line.split("->", 1)[1].strip())
    except (ValueError, IndexError):
        return None
