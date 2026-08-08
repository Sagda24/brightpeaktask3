# context_eval/ — Context Window Management

**Owner:** Person B, Context Engineering Lead
**Depends on:** the existing `memory/` package (this evaluates context fed to
the agent loop, not the persistent memory stores themselves) and the same
BrightPeak Academy domain as `Mcp-Server/server.py` and `DB/`.

## The real problem

BrightPeak's advising agent handles long registration calls. Over many turns
it calls `get_student_profile`, `list_all_courses`, `search_knowledge_base`,
and `generate_academic_report` — each a sizeable JSON/text tool result. Early
in a call a student will often state something that changes what the agent
is allowed to do *later*: an approved prerequisite waiver, a registration
hold that was already cleared, a credit-overload exception, or transferred
credit that was already approved by the registrar. If that fact doesn't
survive to the turn where the agent decides whether to enroll the student,
the agent does the wrong thing — blocks a student who has a waiver, silently
enrolls someone with an unresolved hold, or rejects an already-approved
transfer equivalency. That's a real, costly failure mode, not something that
would show up identically in three lines of throwaway chat.

## What's here

| File | Purpose |
|---|---|
| `transcripts.py` | Builds the fixed, 10-transcript long-context test suite (see below). |
| `strategies/` | All four context management strategies, same interface, same agent. |
| `agent.py` | The final-answer step every strategy is graded against. |
| `metrics.py` | Token/latency cost model (see methodology note below). |
| `run_eval.py` | Runs every strategy × every transcript, produces `results/comparison_table.md` + `results/raw_results.json`. |

Run it: `python3 -m context_eval.run_eval`

## The test suite

10 fixed transcripts (`transcripts.build_test_suite()`), each:
- 69–102 turns, ~3,200–7,400 tokens of mostly tool-call/tool-result JSON
  (large `get_student_profile` dumps, full course lists, knowledge-base
  search hits, academic-report progress), matching the lab's cost note that
  input tokens are the cheap way to build a thorough suite.
- Buries exactly one critical eligibility fact (`critical_marker`) at a
  varied position early in the call (turn 1–5 of the conversation, but
  turns 10s–100s deep once tool noise is counted).
- Ends with the agent asking a final question that can only be answered
  correctly if that fact is still present in whatever context the strategy
  handed to the final-answer step.
- Cycles through all four fact types (`prerequisite_waiver`,
  `registration_hold_cleared`, `credit_overload_exception`,
  `transfer_credit`) across different (fixed, seeded) students and noise
  volumes.

**The suite is fixed once evaluation starts** — the seeds in
`build_test_suite()` are pinned for reproducibility, per the lab's guardrail
against changing test cases between runs.

## Methodology note (read before trusting the numbers)

This sandbox has no network access and no LLM API key, so `context_eval`
cannot place live completion calls the way a production eval harness would.
Two different things are measured two different ways:

1. **Accuracy is measured directly and deterministically.** The final-answer
   step (`agent.py`) is only allowed to answer using text literally present
   in whatever context a strategy produced. If `critical_marker` isn't a
   substring of the pruned context, the answer is wrong — exactly the
   property a real grounded LLM call would also depend on. Nothing about the
   accuracy numbers is simulated.
2. **Tokens and latency use a documented, auditable cost model** (see
   `metrics.py`), calibrated to typical completion-endpoint behavior: input
   tokens are cheap, a completion call costs a fixed base latency, and each
   *extra* LLM call a strategy needs internally (recursive summarization's
   compression passes) adds its own latency and output tokens. This is not a
   black box — the formula is four lines of arithmetic in `metrics.py` and
   the assumptions are stated there.

## Results

10-transcript suite, all four strategies against the same agent:

| Strategy | Critical fact recalled correctly | Avg. input tokens/run | Avg. output tokens/run | Avg. latency |
|---|---|---|---|---|
| Sliding window (last 10 turns) | 0/10 | 544 | 40 | 0.77s |
| Observation/tool-output masking (keep last 3) | 10/10 | 1,504 | 40 | 0.88s |
| Recursive summarization (compact every 15 turns) | 10/10 | 1,364 | 569 | 3.67s |
| Zone-based pruning (4 zones) | 10/10 | 1,651 | 40 | 0.9s |

(regenerate with `python3 -m context_eval.run_eval`; raw per-transcript
results are in `results/raw_results.json`)

### What we ship: observation/tool-output masking

Sliding window is eliminated outright — a plain last-N window loses the
critical fact on **every single transcript**, because it's stated well before
turn N and never revisited. That's the concrete cost of "forgetting" in this
domain: it isn't hypothetical.

Among the three strategies that reliably preserved the fact, masking wins:
it matches BrightPeak's actual failure mode (the bloat is tool JSON, not
dialogue — masking targets exactly that) at the lowest latency and without
the extra LLM calls recursive summarization needs. Recursive summarization
used *fewer* input tokens on average (it collapses old turns into a compact
summary) but paid for it with 14× the output tokens and ~4× the latency of
masking, because every compression pass is its own completion call — the
same tradeoff the lab's own worked example calls out. Zone-based pruning
tied on accuracy but cost slightly more latency and tokens than masking for
no additional benefit given this transcript shape (most of BrightPeak's
"important" turns are dialogue turns near the fact, which masking's
"keep all dialogue" rule already protects for free — zoning's extra pinned-
zone bookkeeping doesn't buy anything masking wasn't already doing here).

If BrightPeak's real call transcripts skewed toward *dialogue*-heavy bloat
(long rambling conversations rather than tool-JSON-heavy calls), zone-based
pruning's explicit keyword-pinning would likely overtake masking, since
masking only protects tool output, not dialogue volume — worth re-running
this suite against real call logs once they exist, rather than assuming the
choice here generalizes forever.
