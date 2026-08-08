from abc import ABC, abstractmethod


class ContextStrategy(ABC):
    """Every strategy takes the FULL transcript (as the agent would have
    accumulated it turn by turn) and returns what actually gets handed to the
    final-answer LLM call, plus any extra cost it incurred producing that
    (extra_output_tokens / extra_llm_calls -- nonzero only for strategies that
    need their own internal LLM calls, i.e. recursive summarization)."""

    name = "base"

    @abstractmethod
    def apply(self, turns: list) -> dict:
        """Returns {'pruned_turns': [...], 'extra_output_tokens': int,
        'extra_llm_calls': int, 'notes': str}"""
        raise NotImplementedError

