# Self-Correction Evaluation

Same pattern as `retrieval_evaluate/` and `planning_evaluation/`: one fixed
test set (`test_cases.json`), every configuration run against the exact
same cases, results written to `results.json` / `results.csv`.

## What's compared

A 2×2 grid over the two axes `self_correction/` introduces:

- **Algorithm**: Self-Refine vs Reflexion (`self_correction/self_refine.py`,
  `self_correction/reflexion.py`)
- **Feedback**: grounded vs ungrounded (`self_correction/environment.py`)

## Test set

8 fixed `check_prerequisites` / `credit_load` cases against the real
`DB/db/brightpeak.db` (`test_cases.json`), split intentionally 4
genuinely-eligible / 4 genuinely-ineligible so an "always guess yes"
failure mode is neither hidden nor exaggerated by the test set. Only
read-only tools are used — `enroll` is never called here, so the
evaluation never mutates the real database (contrast: `planning`'s own
divergence demo runs enroll against a throwaway DB copy; this evaluation
sidesteps the need for that entirely by not exercising write tools).

## Model used

`self_correction_evaluation/eval_mock_llm.py` — a deterministic offline
stand-in (see that file's docstring for why its behavior — optimistic
first guess, grounded-on-refine — is a fair stand-in for what a real
model does under critique). To reproduce these numbers with a live model
instead, swap `GeneralMockLLM()` for `planning.llm_client.AnthropicLLM()`
in `evaluate_self_correction.py` (requires `ANTHROPIC_API_KEY`); nothing
else needs to change.

## Metrics

- **Accuracy** — fraction of cases whose *final* candidate actually
  matches the real, grounded ground truth, checked independently of which
  environment produced it (`GroundedEnvironment.is_correct`, no LLM
  call). This is the metric that exposes the gap an environment's own
  `converged` flag can hide: an ungrounded run can converge while still
  being wrong.
- **Avg Iterations** — mean Self-Refine iterations / Reflexion trials
- **Avg LLM Calls**, **Avg Tokens**, **Avg Latency (ms)** — cost per case

## Results

Run: `python -m self_correction_evaluation.evaluate_self_correction`

| Configuration | Accuracy | Avg Iterations | Avg LLM Calls | Avg Tokens | Avg Latency (ms) |
|---|---|---|---|---|---|
| Self-Refine / grounded | 1.00 | 1.50 | 2.00 | 149.6 | 0.46 |
| Self-Refine / ungrounded | 0.50 | 1.00 | 2.00 | 135.0 | 0.07 |
| Reflexion / grounded | 1.00 | 1.50 | 2.50 | 204.0 | 0.35 |
| Reflexion / ungrounded | 0.50 | 1.00 | 2.00 | 141.0 | 0.05 |

(`results.csv` / `results.json` in this folder are the raw generated
files backing this table — regenerate by re-running the script above.)

## Reading the result

Both grounded configurations hit 1.00 accuracy: every wrong first guess
gets caught and corrected against the real transcript before the loop
stops. Both ungrounded configurations sit at 0.50 — exactly the fraction
of the test set that was genuinely eligible, because the ungrounded judge
rubber-stamps the optimistic first guess regardless of whether it happens
to be right; it "converges" on the wrong answer with the same confidence
as the right one. That 0.50 isn't a property of Self-Refine or Reflexion
as algorithms — it's what happens whenever *either* algorithm is paired
with a judge that has no way to check its own guess.

The cost of grounding here is modest with this mock model (~1.1–1.25x the
LLM calls, since only genuinely-wrong cases need a second round) — but the
mock's "gets it right immediately once grounded" refine step is a
best-case stand-in for a real model; a real model may need more than one
grounded round on harder cases, which is exactly the kind of thing running
this evaluation against a live model (see above) would reveal that a mock
cannot.

Reflexion costs slightly more than Self-Refine per case here
(one extra LLM call on average) because it always spends a separate call
generating the verbal reflection text before the next trial, even though
in this task family the *next attempt* ends up computed the same
grounded way Self-Refine's refine step is. That extra cost is expected to
pay off more on tasks that recur across many *different* nodes of the
same tool type — where a reflection learned once is reused by every
later node sharing that `ReflexionMemory` (see `integration.py`) — which
this single-node-per-case test set does not exercise.
