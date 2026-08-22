"""
Knowledge-base storage.

knowledge_base.json is the single source of truth for RAG documents.
load_knowledge_base() has existed since the original project. This file
now also owns the write path (add_document / remove_document) so every
caller — the MCP server's admin tools, tests, scripts — goes through the
same validated, lock-protected read-modify-write instead of hand-editing
the JSON file directly.

A write here does NOT, by itself, update the BM25 / FAISS indexes that
were already built in memory (server.py, rag/naive_rag.py, rag/hybrid_rag.py
all snapshot the knowledge base once at import time). Callers that need the
retrieval layer to reflect a change must also call the relevant rebuild()
functions — see Mcp-Server/server.py's add_knowledge_document /
remove_knowledge_document tools, which do exactly that.
"""

import json
import threading
from pathlib import Path

_KB_PATH = Path(__file__).parent / "knowledge_base.json"

# Guards read-modify-write of the JSON file against concurrent tool calls.
_lock = threading.Lock()

_REQUIRED_FIELDS = {"id", "title", "text"}


def load_knowledge_base():
    with open(_KB_PATH, "r", encoding="utf-8") as file:
        return json.load(file)


def _save_knowledge_base(documents):
    # Write to a temp file then replace, so a crash mid-write can't leave
    # knowledge_base.json truncated/corrupt.
    tmp_path = _KB_PATH.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as file:
        json.dump(documents, file, indent=2, ensure_ascii=False)
    tmp_path.replace(_KB_PATH)


def add_document(document: dict) -> dict:
    """Adds a new policy document to the knowledge base.

    Raises ValueError if a required field is missing or the id already
    exists — callers (the MCP tool) turn that into a status='error' reply
    instead of letting it crash the tool call.
    """
    missing = _REQUIRED_FIELDS - document.keys()

    if missing:
        raise ValueError(
            f"document is missing required fields: {sorted(missing)}"
        )

    document = {
        "id": str(document["id"]),
        "title": document["title"],
        "text": document["text"],
        "category": document.get("category", "general"),
        "department": document.get(
            "department",
            "Academic Affairs"
        ),
    }

    with _lock:
        documents = load_knowledge_base()

        if any(
            doc["id"] == document["id"]
            for doc in documents
        ):
            raise ValueError(
                f"document id '{document['id']}' already exists"
            )

        documents.append(document)
        _save_knowledge_base(documents)

    return document


def remove_document(document_id: str) -> bool:
    """Removes a document by id. Returns True if something was removed."""

    document_id = str(document_id)

    with _lock:
        documents = load_knowledge_base()

        remaining = [
            doc
            for doc in documents
            if doc["id"] != document_id
        ]

        if len(remaining) == len(documents):
            return False

        _save_knowledge_base(remaining)

    return True


def list_documents() -> list:
    return [
        {
            "id": doc["id"],
            "title": doc["title"],
            "category": doc.get(
                "category",
                "general"
            ),
        }
        for doc in load_knowledge_base()
    ]


if __name__ == "__main__":
    documents = load_knowledge_base()

    print("Number of documents:", len(documents))

    for document in documents:
        print(
            document["id"],
            "-",
            document["title"]
        )
