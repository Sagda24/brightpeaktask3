from .base import ContextStrategy

MASK_TEMPLATE = "[tool result masked: earlier {tool_name} output omitted to save context]"


class ObservationMaskingStrategy(ContextStrategy):
    """Keep every dialogue turn in full (dialogue is cheap and where the real
    signal lives for BrightPeak's advising calls); keep only the most recent
    N tool_result turns in full and replace older ones with a short mask.
    This targets the actual failure mode here: bloat is tool JSON, not
    dialogue, so masking the JSON preserves the fact while shrinking tokens."""

    name = "observation_masking"

    def __init__(self, keep_last_tool_outputs: int = 3):
        self.keep_last_tool_outputs = keep_last_tool_outputs

    def apply(self, turns: list) -> dict:
        tool_result_indices = [i for i, t in enumerate(turns) if t["type"] == "tool_result"]
        keep_set = set(tool_result_indices[-self.keep_last_tool_outputs:]) if tool_result_indices else set()

        pruned = []
        masked_count = 0
        for i, t in enumerate(turns):
            if t["type"] == "tool_result" and i not in keep_set:
                pruned.append({
                    **t,
                    "content": MASK_TEMPLATE.format(tool_name=t.get("tool_name") or "tool"),
                })
                masked_count += 1
            else:
                pruned.append(t)

        return {
            "pruned_turns": pruned,
            "extra_output_tokens": 0,
            "extra_llm_calls": 0,
            "notes": f"masked {masked_count} of {len(tool_result_indices)} tool results, "
                     f"kept last {self.keep_last_tool_outputs} in full; all dialogue kept",
        }
