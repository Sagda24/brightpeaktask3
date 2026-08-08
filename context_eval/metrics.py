LATENCY_BASE_S = 0.15
LATENCY_PER_1K_INPUT_TOKENS_S = 0.12
LATENCY_PER_LLM_CALL_S = 0.55
FINAL_ANSWER_OUTPUT_TOKENS = 40


def approx_tokens(text: str) -> int:
    """Rough token estimate (no tokenizer library available offline).
    ~4 chars/token is the standard rule-of-thumb approximation."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def context_tokens(pruned_turns) -> int:
    return sum(approx_tokens(t.get("content", "")) for t in pruned_turns)


def score_run(pruned_turns, extra_output_tokens: int, extra_llm_calls: int) -> dict:
    """Given what a strategy handed to the final-answer call, compute the
    token and latency cost of that run under the documented cost model."""
    input_tokens = context_tokens(pruned_turns)
    output_tokens = extra_output_tokens + FINAL_ANSWER_OUTPUT_TOKENS
    total_llm_calls = extra_llm_calls + 1  # +1 for the final answer call itself

    latency = (
        LATENCY_BASE_S
        + (input_tokens / 1000) * LATENCY_PER_1K_INPUT_TOKENS_S
        + total_llm_calls * LATENCY_PER_LLM_CALL_S
    )

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "llm_calls": total_llm_calls,
        "latency_s": round(latency, 3),
    }
