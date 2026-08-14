# Registration & Degree-Progress Planning Agent

A second, separate agent on top of the same `Mcp-Server/`, `DB/`, and reference
toolkit already used by the memory/RAG agent (see the top-level `README.md`).
This one owns a **planning** problem, not a retrieval problem.

## The real problem

Brightpeak students routinely email or message the registrar something like:

> "Please register me for Software Engineering Principles this semester."

Today nothing in the system can safely resolve that in one call. `enroll_student`
will happily insert the enrollment row for *any* student/course pair — it does not
check the academy's own written prerequisite policy (`PRE-001`), grading policy
(`GRD-001`), or retake policy (`RET-001`) against the student's actual transcript.
A human registrar currently has to: look up the student's transcript, work out
whether the specific course's prerequisite chain is satisfied, decide (if not)
whether the student needs to retake a failed prerequisite first, and only then
enroll them — or reject/redirect the request. That's multiple dependent
decisions, with a real cost to getting it wrong (an ineligible enrollment that
violates policy and has to be manually unwound later).

This is a genuinely different agent and a genuinely different concern from the
memory/RAG agent, which answers policy *questions* ("what's the attendance
policy?") — it never decides or executes a multi-step action on a student's
academic record.

## What Person 1's slice covers (this file + `dag.py` / `decomposition.py` /
`dynamic_decomposition.py` / `prerequisites.py` / `db_tools.py`)

- **`dag.py`** — the one place acyclicity is enforced (`DAG.add_node` /
  `DAG.add_edge` both re-run a full topological sort and roll back on
  `DAGCycleError`) and the one place run traces are serialized
  (`DAG.save_trace` → `artifacts/<method>_<run_id>.json`).
- **`prerequisites.py`** — the grounded facts the DB doesn't store
  (prerequisite chain per course, pass threshold, credit ceiling), sourced
  from the academy's own `PRE-001` / `GRD-001` policies.
- **`db_tools.py`** — real handlers. `tool_enroll` and `tool_search_policy`
  call the *existing* `Mcp-Server/server.py` tools directly (no duplicated
  logic); `tool_check_prerequisites` and `tool_credit_load` are new grounded
  checks against the real database, not an LLM's opinion.
- **`decomposition.py`** — decomposition-first: one LLM call produces the
  *whole* plan up front (`decompose_first`), which is then executed strictly
  in topological order (`execute_dag`) with no re-planning.
- **`dynamic_decomposition.py`** — dynamic/interleaved: one sub-task is
  generated, executed against the real tool, and its real result is fed back
  before the next sub-task is generated (`dynamic_decompose_and_execute`).
  A course-of-action change is logged as a `replan` event in the trace.

## The divergence (`demo_divergence.py`)

Same request, same student (`student_id=7`, Kareem Reda — transcript shows a
45.0/DROPPED attempt at *Introduction to Computer Science*, below the 60.0
pass threshold), same target course (*Software Engineering Principles*, which
requires passing *Introduction to Computer Science*):

| Method | What happened | LLM calls | Tokens |
|---|---|---|---|
| Decomposition-first | Generated a fixed 3-step plan (`get_profile → check_prerequisites → enroll`) once. `check_prerequisites` correctly reported the student ineligible — but the plan had no branch for that, so `enroll` still ran next and **the ineligible enrollment succeeded anyway**. | 1 | 191 |
| Dynamic decomposition | Generated `get_profile`, then `check_prerequisites`, observed the real `eligible: false` result, and generated a **new** step checking the missing prerequisite instead of proceeding to the originally requested enrollment. No bad enrollment was written. | 4 | 701 |

Dynamic decomposition costs ~3.7x the tokens and 4x the LLM calls here — the
real trade-off this lab asks for: decomposition-first is cheap and fine for
the fully mechanical requests (e.g. a student who already meets every
prerequisite), dynamic decomposition earns its extra cost specifically when a
sub-task result can actually change what should happen next, which is exactly
the shape of this request type.

Run it:
```bash
python -m planning.demo_divergence
python -m pytest planning/test_dag.py -q   # cycle/ordering unit tests
```

Both commands run against a throwaway copy of `DB/db/brightpeak.db` — nothing
is permanently written to the real academy database by the demo.

## Model provider

`llm_client.py` exposes one call signature (`call(prompt) -> LLMResponse`)
behind three providers: `McpSamplingLLM` (production — reuses this repo's
existing `ctx.sample()` pattern from `request_student_evaluation`),
`AnthropicLLM` (for offline batch evaluation in `planning_eval/`), and
`MockLLM` (deterministic, offline — used only by `demo_divergence.py` so the
divergence above is reproducible without network/API access; **not** what the
system ships with).

## Not yet in this slice

Routing sub-tasks to Plan-and-Solve / Tree of Thoughts / LATS, Self-Refine /
Reflexion, and the grounded-vs-ungrounded critique comparison are separate
concerns (owned by the planning-algorithm and self-correction slices) that sit
on top of the same DAG produced here — `Node.suggested_method` is already
populated (`"PS"` for the deterministic prerequisite check, `null` for the
mechanical enroll step) so that routing layer has something real to key off.

# Planning Algorithms

This module implements the planning algorithms required for the Autonomous Agent project.

The planning layer is responsible for selecting an appropriate reasoning strategy for each decomposed sub-task and executing it through the available tools/environment.

## Implemented Algorithms

### 1. Plan-and-Solve

Plan-and-Solve uses a single explicit planning phase followed by sequential execution.

Flow:

User Task
→ Understand
→ Generate Plan
→ Execute Plan
→ Final Answer

It is suitable for mostly linear tasks where the required steps are known in advance.

Characteristics:
- Single plan
- No branching
- No backtracking
- Low computational cost
- Clear execution order

---

### 2. Tree of Thoughts (ToT)

Tree of Thoughts extends single-path reasoning into a search tree.

Flow:

Current State
→ Generate Candidate Thoughts
→ Evaluate Candidates
→ Select Best Candidates
→ Expand
→ Repeat

The implementation uses beam search to control the number of branches explored.

Main parameters:
- `beam_width`: number of candidates kept at each level
- `depth`: maximum search depth
- `n_candidates`: number of candidates generated per state

ToT is suitable for tasks where lookahead and exploration are important.

Characteristics:
- Multiple candidate plans
- Branching
- Candidate evaluation
- Pruning
- Backtracking/search
- Higher cost than Plan-and-Solve

---

### 3. Language Agent Tree Search (LATS)

LATS combines language-model reasoning with Monte Carlo Tree Search (MCTS) and external environment feedback.

Flow:

Select
→ Expand + Simulate
→ Evaluate with External Feedback
→ Reflect on Failure
→ Backpropagate
→ Continue Search

Unlike ToT, LATS does not rely only on the language model to judge whether a solution is good. It uses feedback from the environment, such as validation results, tool results, tests, or database constraints.

Characteristics:
- MCTS-based search
- Multiple action trajectories
- External environment feedback
- Reflection on failed branches
- Backpropagation of rewards
- Highest computational cost among the three methods

---

## Planning Router

The router selects the planning algorithm based on the characteristics of the sub-task.

### Routing Strategy

- **Mostly linear task** → Plan-and-Solve
- **Task requiring lookahead/exploration** → Tree of Thoughts
- **Task with a checkable environment and external feedback** → LATS

The router can also respect an explicitly suggested planning method provided by the decomposition/DAG layer.

---

## Integration with the DAG

The planning module is designed to work after the decomposition layer.

Overall flow:

Goal
→ Task Decomposition
→ DAG
→ Planning Router
→ Plan-and-Solve / ToT / LATS
→ Tool Execution
→ Verification
→ Final Result

The DAG provides the sub-tasks and their dependencies, while the planning layer decides how each sub-task should be solved.

---

## Evaluation

The `planning_eval` module compares the implemented planning algorithms using a fixed set of test cases.

The evaluation considers:

- Task success
- Number of LLM calls
- Token usage
- Latency
- Estimated cost

The purpose of the evaluation is to determine which planning strategy provides the best trade-off between quality, reasoning capability, and computational cost.

---

## Files

```text
planning/
├── plan_and_solve.py
├── tree_of_thoughts.py
├── lats.py
├── router.py
├── test_planning_algorithms.py
└── README.md

planning_eval/
├── evaluate_planning.py
├── test_cases.json
├── results.json
└── README.md
