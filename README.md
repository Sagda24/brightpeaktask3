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
