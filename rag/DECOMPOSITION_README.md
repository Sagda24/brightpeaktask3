# Decomposition Add-On (Option A: Query Decomposition)

## What's here

- `rag/query_decomposition.py` — `DECOMPOSE_PROMPT` and `parse_sub_questions()`,
  pure prompt/parsing logic, no LLM client and no network call baked in.
- `Mcp-Server/server.py` — the real `decompose_and_search` MCP tool, added
  right after `search_knowledge_base`. It does not replace that tool; it
  calls it once per sub-question.
- `rag/decompose_and_search_demo.py` — standalone demo, runs with
  `python3 -m rag.decompose_and_search_demo`, no MCP session needed.

## How the real LLM call works

This repo has no Anthropic/OpenAI API key and no network egress configured
(no `requirements.txt` entry for either, no `.env`). The one real LLM call
already in this codebase is **MCP sampling** — `Mcp-Server/server.py`'s
`request_student_evaluation` tool already uses `ctx.sample(...)` to ask the
*connected client's* model to do something server-side can't. `decompose_and_search`
uses the exact same mechanism for its one decomposition call:

```python
sample_response = await ctx.sample(messages=prompt, max_tokens=200)
sub_questions = parse_sub_questions(sample_response.text) or [query]
```

This is a real LLM call (whatever model the connecting client provides, same
as `request_student_evaluation`'s), not a new dependency.

## Why `search_knowledge_base` needed a small refactor

FastMCP's `@mcp.tool()` decorator returns a `Tool` object, not the original
Python function — so `search_knowledge_base(...)` isn't directly callable
from other Python code once decorated (confirmed against FastMCP's own
"Decorating Methods" docs). The tool's search logic was pulled out into
`_search_knowledge_base_impl(query, top_k)`, a plain function; the
`@mcp.tool()`-decorated `search_knowledge_base` is now a one-line wrapper
around it, and `decompose_and_search` calls `_search_knowledge_base_impl`
directly, once per sub-question. `search_knowledge_base`'s registered
behavior, name, and schema are unchanged.

## The demo

`python3 -m rag.decompose_and_search_demo` runs against the real
`rag/knowledge_base/knowledge_base.json` and a real BM25 index (a small
BM25Okapi-compatible reimplementation with the same k1/b defaults as
`rank_bm25`, used only so the demo has no extra dependency — the real tool
in `server.py` uses the actual `rank_bm25` index the server already builds).
The decomposition step in the demo is a rule-based stand-in for the real
`ctx.sample()` call (there's no live MCP session to sample from outside the
server), documented in the file itself — everything downstream of it
(the search calls, the scores, which documents get recovered) is real.

Demo query: *"What attendance percentage is required to sit the final exam,
and what happens if I fail the course afterward?"*

Plain `search_knowledge_base` (top_k=3) returns Grading Policy, Course Retake
Policy, and Attendance Policy — it misses **Final Examination Eligibility**,
the single most on-point document, because the compound query's mixed
vocabulary dilutes the BM25 score for either half of the question.

`decompose_and_search` splits it into two sub-questions, searches each
separately, and recovers **Final Examination Eligibility**, **Course
Withdrawal Policy**, and **Academic Policy Reference Guide** — three
documents the plain top-3 search missed entirely — tagged with which
sub-question each one answers, exactly as required:

```
sub-questions: ['What attendance percentage is required to sit the final exam?',
                'what happens if I fail the course afterward?']
[What attendance percentage is required to sit the final exam?] -> [4.91] Attendance Policy
[What attendance percentage is required to sit the final exam?] -> [4.8]  Final Examination Eligibility
[What attendance percentage is required to sit the final exam?] -> [4.14] Academic Policy Reference Guide
[what happens if I fail the course afterward?] -> [2.77] Course Retake Policy
[what happens if I fail the course afterward?] -> [2.75] Grading Policy
[what happens if I fail the course afterward?] -> [0.98] Course Withdrawal Policy
```

`decompose_and_search` does not merge these into one answer — the tagged,
combined chunk list is the tool's output, exactly as the spec asks; letting
the calling model synthesize the final answer is deliberate.
