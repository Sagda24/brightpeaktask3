from .base import ContextStrategy


class SlidingWindowStrategy(ContextStrategy):
    """Keep only the last N turns verbatim. Cheapest strategy, but a fact
    stated early in a long call is gone the moment it scrolls out of the
    window -- no notion of importance at all."""

    name = "sliding_window"

    def __init__(self, window: int = 10):
        self.window = window

    def apply(self, turns: list) -> dict:
        pruned = turns[-self.window:] if len(turns) > self.window else list(turns)
        return {
            "pruned_turns": pruned,
            "extra_output_tokens": 0,
            "extra_llm_calls": 0,
            "notes": f"kept last {len(pruned)} of {len(turns)} turns",
        }
