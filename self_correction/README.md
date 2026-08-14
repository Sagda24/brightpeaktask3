# Self-Correction Layer — Self-Refine, Reflexion, Grounded Environment

The self-correction slice flagged in `planning/README.md` as "not yet in
this slice" (Self-Refine / Reflexion, and the grounded-vs-ungrounded
critique comparison). It sits **on top of** the existing DAG/Node
execution model — it does not replace or duplicate it.

## The real problem

`planning/db_tools.py` already has a comment on `tool_check_prerequisites`
calling it "the environment feedback source that later replaces the
toolkit's randomized environment.py default." That is exactly the gap this
slice fills: a step in a plan can produce a *candidate* result (an LLM's
best guess at "is this student eligible?") that **sounds** right without
**being** right — and the only way to catch that is to check it against
something real. Whether that check happens or not is the entire
grounded-vs-ungrounded distinction below.

## Files

```text
self_correction/
├── environment.py    # Environment (ungrounded) / GroundedEnvironment
├── self_refine.py     # generate -> critique -> refine, ONE working candidate
├── reflexion.py        # trial -> reflect -> retry, verbal memory across trials
├── integration.py      # wires both into planning.dag.Node execution
├── mock_llm.py          # deterministic offline LLM for tests/demo
├── test_self_correction.py
└── demo_grounded_vs_ungrounded.py
```

## Environment: grounded vs ungrounded

Both `SelfRefine` and `Reflexion` are written against one interface,
`environment.evaluate(task, candidate) -> Feedback`, and know nothing
about *how* that feedback is produced:

- **`Environment`** (ungrounded, the default) — the critique is the LLM's
  own opinion of its own output. No tool is called. Cheap, but the same
  model that made a mistake is also the one grading it.
- **`GroundedEnvironment`** — re-derives the real answer via the actual
  `planning.db_tools.TOOL_REGISTRY` handler for that task (the same
  functions `dynamic_decomposition.py` already calls against the live
  database and the academy's own PRE-001/GRD-001/RET-001 policies) and
  compares the candidate against it. The LLM is only used to phrase the
  mismatch as a sentence — never to decide pass/fail.

Swapping `grounded=True/False` is the one flag that produces the
grounded-vs-ungrounded comparison; see `demo_grounded_vs_ungrounded.py`
and `self_correction_evaluation/`.

## Self-Refine vs Reflexion

Both correct a candidate answer, but differently, and the code makes
that difference structural rather than a matter of prompt wording:

| | Self-Refine | Reflexion |
|---|---|---|
| Unit of correction | one candidate, rewritten in place | a fresh, independent trial each time |
| What carries forward | the immediately preceding critique | an accumulating list of verbal reflections (`ReflexionMemory`), across trials **and** across tasks of the same tool type |
| Shape | `generate -> critique -> refine -> critique -> ...` | `attempt -> evaluate -> reflect -> attempt -> ...` |
| Stops when | `feedback.passed` or `score >= threshold` or `max_iterations` | same, but over `max_trials` |

`ReflexionMemory` deliberately mirrors the shape of `memory/episodic.py`
(a list of `{task_key, reflection}` entries) so it could be backed by that
module's `EpisodicMemory` in a later integration without changing this
file's interface — it is not wired to it here, since that memory module
is keyed by `student_id`/conversational events, a different concern from
per-tool-type verbal lessons.

## Integration with the DAG

`integration.execute_node(node, dag, llm, grounded=...)` is a drop-in
replacement for the direct-tool-call block already inside
`dynamic_decomposition.py`'s loop:

- `node.suggested_method == "SelfRefine"` → routed through `SelfRefine`
- `node.suggested_method == "Reflexion"` → routed through `Reflexion`
  (all nodes of one `run_dag_with_correction()` call share a single
  `ReflexionMemory`, so a reflection learned on one node is available to
  a later node of the same tool)
- anything else (the existing `"PS"` / `"ToT"` / `"LATS"` / `None`
  values) → unchanged, calls `TOOL_REGISTRY[node.tool]` directly, exactly
  like today

Every correction run logs onto the DAG's own trace (`dag.log_event`,
`dag.llm_calls`, `dag.total_tokens`) — one trace format for the whole
project (`artifacts/<method>_<run_id>.json`), not a second one for this
slice.

## Why this doesn't touch a real student record during testing

`self_correction/`'s tests and demo only exercise `check_prerequisites`
(a read-only, grounded query) — never `enroll`, which writes to
`DB/db/brightpeak.db`. The evaluation harness in
`self_correction_evaluation/` follows the same rule; see its README for
why.

## Run it

```bash
python -m self_correction.demo_grounded_vs_ungrounded
python -m pytest self_correction/test_self_correction.py -q
```
