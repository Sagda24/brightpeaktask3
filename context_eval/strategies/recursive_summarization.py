from .base import ContextStrategy
from ..metrics import approx_tokens

# Same spirit as memory/router.py's importance keywords, extended with the
# advising-call vocabulary this transcript suite actually uses. A real
# summarization call would be an LLM prompted to compress the chunk while
# preserving decision-relevant facts -- here (no LLM available offline) we do
# that extractively: keep any turn matching these markers verbatim inside the
# running summary, and compress everything else into a one-line stub.
IMPORTANT_KEYWORDS = [
    "waiver", "hold", "exception", "transfer credit", "cleared",
    "approved", "prerequisite", "overload", "credit",
]


def _is_important(content: str) -> bool:
    low = content.lower()
    return any(kw in low for kw in IMPORTANT_KEYWORDS)


class RecursiveSummarizationStrategy(ContextStrategy):
    """Every `compress_every` turns, fold the oldest not-yet-summarized chunk
    into a running summary (one real LLM call per compression pass -- the
    extra cost the lab specifically calls out: output tokens and latency go
    up because summarization itself requires generation, not just masking).
    Important turns are kept verbatim inside the summary; everything else in
    that chunk collapses to a short stub line."""

    name = "recursive_summarization"

    def __init__(self, compress_every: int = 15, keep_recent_full: int = 15):
        self.compress_every = compress_every
        self.keep_recent_full = keep_recent_full

    def _summarize_chunk(self, chunk: list) -> str:
        lines = ["[running summary of earlier turns]"]
        for t in chunk:
            if t["type"] == "dialogue" and _is_important(t["content"]):
                lines.append(f"- (t{t['turn']}, {t['speaker']}) {t['content']}")
            elif t["type"] == "tool_result" and _is_important(t["content"]):
                lines.append(f"- (t{t['turn']}, tool={t.get('tool_name')}) relevant result: {t['content'][:120]}")
        if len(lines) == 1:
            lines.append(f"- ({len(chunk)} turns of routine tool calls / small talk, nothing decision-relevant)")
        return "\n".join(lines)

    def apply(self, turns: list) -> dict:
        n = len(turns)
        cutoff = max(0, n - self.keep_recent_full)
        old_chunk = turns[:cutoff]
        recent = turns[cutoff:]

        extra_calls = 0
        extra_output_tokens = 0
        summary_turns = []

        if old_chunk:
            # one compression pass per compress_every-sized block of the old
            # portion -- this is the "periodic, chunked" recursive part
            for start in range(0, len(old_chunk), self.compress_every):
                block = old_chunk[start:start + self.compress_every]
                summary_text = self._summarize_chunk(block)
                extra_calls += 1
                extra_output_tokens += approx_tokens(summary_text)
                summary_turns.append({
                    "turn": block[0]["turn"], "speaker": "system", "type": "summary",
                    "tool_name": None, "content": summary_text, "is_critical": False,
                })

        pruned = summary_turns + recent
        return {
            "pruned_turns": pruned,
            "extra_output_tokens": extra_output_tokens,
            "extra_llm_calls": extra_calls,
            "notes": f"compressed {len(old_chunk)} old turns into {len(summary_turns)} "
                     f"summary block(s) via {extra_calls} extra LLM call(s); "
                     f"kept last {len(recent)} turns verbatim",
        }
