from rag.knowledge_base.loader import load_knowledge_base
from rag.vector_store import VectorStore

from sentence_transformers import SentenceTransformer


# ============================================================
# CONFIGURATION
# ============================================================

EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"

CHUNK_SIZE = 500
CHUNK_OVERLAP = 100

TOP_K = 3


# ============================================================
# CHUNKING
# ============================================================

def create_chunks(
    documents,
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP
):
    chunks = []

    for document in documents:

        text = document["text"]

        start = 0

        while start < len(text):

            end = start + chunk_size

            chunk_text = text[start:end]

            chunks.append({
                "document_id": document["id"],
                "title": document["title"],
                "category": document.get(
                    "category",
                    "general"
                ),
                "department": document.get(
                    "department",
                    "Academic Affairs"
                ),
                "text": chunk_text
            })

            start += (
                chunk_size - chunk_overlap
            )

    return chunks


# ============================================================
# BUILD VECTOR STORE
# ============================================================

def build_vector_store():

    documents = load_knowledge_base()

    chunks = create_chunks(documents)

    embedding_model = SentenceTransformer(
        EMBEDDING_MODEL_NAME
    )

    chunk_texts = [
        chunk["text"]
        for chunk in chunks
    ]

    embeddings = embedding_model.encode(
        chunk_texts,
        convert_to_numpy=True,
        normalize_embeddings=True
    )

    dimension = embeddings.shape[1]

    vector_store = VectorStore(
        dimension
    )

    vector_store.add(
        embeddings,
        chunks
    )

    return (
        embedding_model,
        vector_store,
        chunks
    )


# ============================================================
# NAIVE RAG RETRIEVAL
# ============================================================

embedding_model, vector_store, chunks = (
    build_vector_store()
)


def retrieve(query, top_k=TOP_K):

    query_embedding = embedding_model.encode(
        [query],
        convert_to_numpy=True,
        normalize_embeddings=True
    )

    return vector_store.search(
        query_embedding,
        top_k=top_k
    )


# ============================================================
# CONTEXT BUILDER
# ============================================================

def build_context(results):

    context_parts = []

    for result in results:

        context_parts.append(
            f"[Source: {result['title']}]\n"
            f"{result['text']}"
        )

    return "\n\n".join(
        context_parts
    )


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    print("Documents:", len(
        load_knowledge_base()
    ))

    print("Chunks:", len(chunks))

    question = (
        "What attendance percentage "
        "is required to take the final exam?"
    )

    results = retrieve(
        question,
        top_k=3
    )

    print("\nQUESTION:")
    print(question)

    print("\nRETRIEVED:")

    for i, result in enumerate(
        results,
        start=1
    ):

        print("\n-------------------")
        print("Rank:", i)
        print("Document:", result["document_id"])
        print("Title:", result["title"])
        print("Score:", result["score"])
        print("Text:", result["text"])