# Brightpeak Academy — MCP Agent with Memory & RAG

An extension of the Brightpeak Academy MCP Server that adds long-term memory, grounded knowledge retrieval, multiple RAG architectures, context management, query decomposition, and Self-RAG-style verification.

The system is designed to help an academic assistant answer questions using both structured student data stored in the existing SQLite database and unstructured academic policies stored in a knowledge base.

---

## 1. Project Overview

Brightpeak Academy already provides an MCP server that exposes academic operations such as:

- Student profile lookup
- Course listing
- Course enrollment
- Grade updates
- Academic report generation
- Student academic evaluation

The main limitation of the original system is that the assistant can only reason over information returned directly from tools.

Academic policies such as attendance requirements, grading rules, registration restrictions, prerequisites, withdrawal policies, and graduation requirements are not naturally represented as database operations.

This extension introduces a retrieval and memory layer so the agent can:

1. Retrieve relevant academic policies.
2. Compare multiple retrieval architectures.
3. Handle compound questions through query decomposition.
4. Verify whether retrieved information is actually relevant.
5. Verify whether generated answers are supported by retrieved evidence.
6. Preserve useful information beyond a single conversation.
7. Manage long conversational context.
8. Evaluate retrieval quality using a fixed domain-specific test set.

The extension reuses the existing MCP server and SQLite database rather than rebuilding the original system.

---

# 2. Architecture

```text
                         ┌──────────────────────┐
                         │     User Query       │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │     MCP Client       │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │    MCP Server        │
                         │  Brightpeak Academy  │
                         └──────────┬───────────┘
                                    │
                    ┌───────────────┴────────────────┐
                    │                                │
                    ▼                                ▼
          ┌──────────────────┐             ┌──────────────────┐
          │ SQLite Database  │             │   RAG Layer      │
          │                  │             │                  │
          │ Students         │             │ Knowledge Base   │
          │ Courses          │             │ Embeddings       │
          │ Enrollments      │             │ Retrieval        │
          │ Grades           │             │ Generation       │
          └──────────────────┘             └────────┬─────────┘
                                                     │
                         ┌───────────────────────────┼───────────────────────────┐
                         │                           │                           │
                         ▼                           ▼                           ▼
                 ┌──────────────┐           ┌──────────────┐           ┌──────────────┐
                 │   Naive RAG  │           │ Hybrid RAG   │           │ Agentic RAG  │
                 └──────────────┘           └──────────────┘           └──────────────┘
                         │                           │                           │
                         └───────────────────────────┼───────────────────────────┘
                                                     ▼
                                          ┌────────────────────┐
                                          │ Self-RAG Verification│
                                          │                    │
                                          │ Retrieval Relevance│
                                          │ Answer Support     │
                                          └──────────┬─────────┘
                                                     │
                                                     ▼
                                           ┌─────────────────┐
                                           │ Grounded Answer │
                                           └─────────────────┘

 3. Repository Structure

brightpeaktask3/
│
├── DB/
│   └── db/
│       └── brightpeak.db
│
├── Mcp-Server/
│   ├── init.py
│   └── server.py
│
├── client/
│   └── client.py
│
├── memory/
│   └── Long-term and conversational memory components
│
├── rag/
│   ├── knowledge_base/
│   │   ├── knowledge_base.json
│   │   └── loader.py
│   │
│   ├── naive_rag.py
│   ├── hybrid_rag.py
│   ├── agentic_rag.py
│   ├── decompose_search.py
│   ├── generation.py
│   ├── self_rag.py
│   └── vector_store.py
│
├── retrieval_evaluate/
│   ├── retrieval_evaluate.py
│   ├── retrieval_questions.json
│   └── results.csv
│
├── context_eval/
│   └── Context management evaluation
│
└── README.md

4.Existing MCP Server

The project keeps the original Brightpeak Academy MCP server and extends it with retrieval capabilities.

The server provides tools including:

get_student_profile
list_all_courses
enroll_student
update_student_grade
generate_academic_report
request_student_evaluation
search_knowledge_base
decompose_and_search

The existing database remains the source of truth for structured academic data

5.Knowledge Base

The RAG system uses a structured academic policy knowledge base
xample policies include:

Attendance Policy
Grading Policy
Course Registration Policy
Academic Warning Policy
Graduation Requirements
Final Examination Eligibility
Course Prerequisite Policy
Course Retake Policy
Course Withdrawal Policy
Registration Restriction Policy
Academic Advising Policy
Certificate Policy
Transcript Policy
Academic Progress Policy
Academic Policy Reference Guide

6. Naive RAG
Question
   ↓
Embedding
   ↓
Vector Search
   ↓
Top-K Documents
   ↓
Context
   ↓
Answer Generation

It is intentionally kept simple so it can serve as the baseline for comparison against more advanced retrieval architectures.



7. Hybrid RAG

Hybrid retrieval combines semantic vector similarity with keyword retrieval.

The keyword component uses BM25

                  Query
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
    Vector Search          BM25 Search
          │                   │
          └─────────┬─────────┘
                    ▼
             Combined Ranking
                    │
                    ▼
              Top-K Results
Hybrid retrieval is particularly useful when users mention exact policy identifiers, course identifiers, or other terms where semantic similarity alone may not be sufficient.


8. Agentic RAG

Agentic RAG introduces an iterative retrieval process.

Instead of performing exactly one retrieval operation, the agent can:

Analyze the question.
Decide what information is needed.
Retrieve relevant documents.
Inspect the retrieved information.
Decide whether another retrieval step is necessary.
Produce the final retrieval result.

This architecture is especially useful for multi-part or multi-hop questions

9. Query Decomposition

The project also supports compound questions through decompose_and_search.

For example:

What are the requirements for registering a course,
and what should a student do if they have a registration restriction?

The system decomposes the query into smaller questions:

1. What are the requirements for registering a course?

2. What should a student do if they have a registration restriction?

Each sub-question is searched independently.

The retrieved chunks remain tagged with their originating sub-question.

The system returns the combined evidence instead of attempting to generate the final answer itself.

This keeps the retrieval layer separate from answer generation.


10. Self-RAG Verification
The project includes explicit retrieval and answer verification.

Retrieval Relevance

After retrieval, the system checks whether the retrieved information is actually relevant to the user's query.

Query
  ↓
Retrieve
  ↓
Check Relevance
  ↓
PASS ──────────► Continue
  │
  └─ FAIL ─────► Reject / Retry
Answer Support

After generating an answer, the system checks whether the claims in the answer are supported by the retrieved evidence.

Retrieved Context
        ↓
   Generate Answer
        ↓
   Check Support
      /      \
   PASS      FAIL
    │          │
    ▼          ▼
 Return      Retry / Refuse
 Answer      Unsupported Answer

The purpose is to prevent the system from confidently answering from unsupported information.

11. Memory Layer

The memory subsystem separates short-term conversational state from long-term memory.

Short-Term Memory

Maintains recent conversation context.

Scratchpad

Stores active working state such as:

Current plan
Current sub-goal
Intermediate reasoning state

The scratchpad is kept separate from the conversation buffer so context pruning does not remove the agent's active state.

Episodic Memory

Stores important events and previous interactions.

Semantic Memory

Stores stable knowledge derived from previous experiences.

Semantic memory is not directly written by the promote-or-drop router.

Instead, it is produced through a separate consolidation process.

12. Context Management

The project evaluates multiple strategies for handling long conversations:

Sliding Window
Observation / Tool Output Masking
Recursive Summarization
Zone-Based Pruning

Each strategy is evaluated using the same test suite.

The comparison considers:

Task accuracy
Token consumption
Latency

The final strategy should be selected based on measured results rather than intuition.

13. Retrieval Evaluation

The project contains a fixed domain-specific retrieval test set:

retrieval_evaluate/
├── retrieval_questions.json
└── retrieval_evaluate.py

Every architecture is evaluated against the same questions:

Naive RAG
Hybrid RAG
Agentic RAG

Metrics include:

Retrieval accuracy
Estimated token usage
Latency
Retrieval rounds

The results are saved to:

retrieval_evaluate/results.csv

The evaluation allows the architectures to be compared using the same questions and evaluation procedure.

14. Why Compare Three Retrieval Architectures?

Each architecture solves a different retrieval problem.

Architecture	Strength
Naive RAG	Simple semantic retrieval
Hybrid RAG	Exact keywords + semantic similarity
Agentic RAG	Multi-step and decomposed queries

The required evaluation asks the system to include questions that exercise each architecture differently and then compare accuracy, token usage, and latency.

15. MCP Integration

The retrieval functionality is exposed through the existing MCP server.

For example:

search_knowledge_base

performs keyword/BM25 retrieval.

The decomposition layer adds:

decompose_and_search

which breaks compound questions into smaller retrieval tasks.

The MCP client can discover and call these tools through the same MCP connection used by the original academic tools.

16. Running the Project
1. Create a virtual environment
python -m venv .venv
2. Activate it

Windows:

.venv\Scripts\activate
3. Install dependencies

Install the packages used by the project, including:

pip install fastmcp
pip install rank-bm25
pip install sentence-transformers

Additional dependencies should be installed according to the final environment used by the project.

17. Run the MCP Server

From the project root:

python Mcp-Server/server.py

The server uses STDIO by default.

HTTP mode can be started with:

python Mcp-Server/server.py http

The HTTP server runs on:

http://127.0.0.1:8000
18. Run the Client
python client/client.py

The client:

Connects to the MCP server.
Lists available tools.
Calls academic database tools.
Tests student evaluation.
Tests knowledge-base retrieval.
Tests decomposed retrieval.
19. Run Retrieval Evaluation

From the project root:

python retrieval_evaluate/retrieval_evaluate.py

The script runs:

Naive RAG
Hybrid RAG
Agentic RAG

against the same evaluation questions.

Results are saved to:

retrieval_evaluate/results.csv
20. Evaluation Results

The final README should include the actual measured results from:

retrieval_evaluate/results.csv

Example format:

Architecture	Accuracy	Avg Tokens	Avg Latency	Avg Retrieval Rounds
Naive RAG	TBD	TBD	TBD	TBD
Hybrid RAG	TBD	TBD	TBD	TBD
Agentic RAG	TBD	TBD	TBD	TBD

The values above should be replaced with the actual experiment results before submission.

21. Design Decisions
Why keep the original MCP server?

The project is an extension of the existing Brightpeak Academy system. Reusing the original database and server avoids duplicating functionality.

Why use a separate knowledge base?

Academic policies are unstructured knowledge and should not require creating a separate MCP tool for every policy.

Why use BM25?

Keyword retrieval is useful for exact terms, policy identifiers, and terminology where semantic similarity may not retrieve the best document.

Why use Agentic RAG?

Some questions contain multiple information needs and may require more than one retrieval step.

Why use Self-RAG verification?

Retrieval alone does not guarantee that the returned documents support the final answer. Explicit relevance and support checks reduce unsupported responses.

22. Safety and Reproducibility
No API keys should be committed.
Environment variables should be stored outside source control.
.env files must be included in .gitignore.
Evaluation questions should remain fixed once benchmarking begins.
The same test set should be used for all retrieval architectures.
Database credentials and other secrets must never be committed.
23. Project Goals

The final system aims to provide:

Persistent memory
Context-aware conversations
Grounded academic knowledge retrieval
Multiple retrieval architectures
Query decomposition
Retrieval verification
Answer-support verification
MCP-based integration
Quantitative evaluation
24. Future Improvements

Possible future extensions include:

More advanced vector database filtering
Better retrieval reranking
More robust answer-support verification
Additional academic knowledge sources
Graph RAG if meaningful entity relationships emerge
More extensive retrieval evaluation


