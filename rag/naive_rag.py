from rag.knowledge_base.loader import load_knowledge_base
from rag.vector_store import VectorStore
from sentence_transformers import SentenceTransformer
from rag.generation import build_rag_prompt
from rag.self_rag import self_rag_verify


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
# INITIALIZE VECTOR STORE
# ============================================================

embedding_model, vector_store, chunks = (
    build_vector_store()
)


# ============================================================
# NAIVE RAG RETRIEVAL
# ============================================================

def retrieve(
    query,
    top_k=TOP_K
):

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
# NAIVE RAG ANSWER
# ============================================================

async def naive_rag_answer(
    query,
    ctx,
    top_k=TOP_K
):

    # --------------------------------------------------------
    # 1. Retrieve
    # --------------------------------------------------------

    results = retrieve(
        query,
        top_k=top_k
    )

    # --------------------------------------------------------
    # 2. Self-RAG retrieval relevance check
    # --------------------------------------------------------

    from rag.self_rag import check_retrieval_relevance

    relevance_check = check_retrieval_relevance(
        query,
        results
    )

    if not relevance_check["passed"]:

        return {
            "status": "verification_failed",
            "stage": "retrieval",
            "verification": relevance_check,
            "results": []
        }

    # --------------------------------------------------------
    # 3. Build grounded RAG prompt
    # --------------------------------------------------------

    prompt = build_rag_prompt(
        query,
        results
    )

    # --------------------------------------------------------
    # 4. Generate answer using MCP client model
    # --------------------------------------------------------

    response = await ctx.sample(
        messages=prompt,
        max_tokens=300
    )

    answer = response.text

    # --------------------------------------------------------
    # 5. Self-RAG support verification
    # --------------------------------------------------------

    verification = self_rag_verify(
        query,
        results,
        answer
    )

    if not verification["approved"]:

        return {
            "status": "verification_failed",
            "stage": "generation",
            "answer": answer,
            "verification": verification,
            "sources": [
                result["document_id"]
                for result in results
            ]
        }

    # --------------------------------------------------------
    # 6. Successful response
    # --------------------------------------------------------

    return {
        "status": "success",
        "answer": answer,
        "sources": [
            {
                "document_id": result["document_id"],
                "title": result["title"]
            }
            for result in results
        ],
        "verification": verification
    }


# ============================================================
# TEST RETRIEVAL
# ============================================================

if __name__ == "__main__":

    documents = load_knowledge_base()

    print(
        "Documents:",
        len(documents)
    )

    print(
        "Chunks:",
        len(chunks)
    )

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

        print(
            "Rank:",
            i
        )

        print(
            "Document:",
            result["document_id"]
        )

        print(
            "Title:",
            result["title"]
        )

        print(
            "Score:",
            result["score"]
        )

        print(
            "Text:",
            result["text"]
        )