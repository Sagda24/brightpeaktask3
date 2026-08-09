from rag.naive_rag import (
    embedding_model,
    vector_store,
    chunks
)

from rank_bm25 import BM25Okapi


# ============================================================
# BM25 INDEX
# ============================================================

tokenized_documents = [
    chunk["text"].lower().split()
    for chunk in chunks
]

bm25 = BM25Okapi(
    tokenized_documents
)


# ============================================================
# VECTOR SEARCH
# ============================================================

def vector_search(
    query,
    top_k=5
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
# BM25 SEARCH
# ============================================================

def keyword_search(
    query,
    top_k=5
):

    query_tokens = (
        query.lower()
        .split()
    )

    scores = bm25.get_scores(
        query_tokens
    )

    ranked_indices = sorted(
        range(len(scores)),
        key=lambda i: scores[i],
        reverse=True
    )

    results = []

    for index in ranked_indices[:top_k]:

        results.append({
            **chunks[index],
            "bm25_score": float(
                scores[index]
            )
        })

    return results


# ============================================================
# NORMALIZATION
# ============================================================

def normalize_scores(
    results,
    score_key
):

    if not results:
        return {}

    scores = [
        result[score_key]
        for result in results
    ]

    minimum = min(scores)
    maximum = max(scores)

    normalized = {}

    for result in results:

        value = result[score_key]

        if maximum == minimum:
            score = 1.0

        else:
            score = (
                (value - minimum)
                /
                (maximum - minimum)
            )

        normalized[
            result["document_id"]
        ] = score

    return normalized


# ============================================================
# HYBRID SEARCH
# ============================================================

def hybrid_search(
    query,
    top_k=3,
    vector_weight=0.6,
    keyword_weight=0.4
):

    vector_results = vector_search(
        query,
        top_k=10
    )

    keyword_results = keyword_search(
        query,
        top_k=10
    )

    vector_scores = normalize_scores(
        vector_results,
        "score"
    )

    keyword_scores = normalize_scores(
        keyword_results,
        "bm25_score"
    )

    all_documents = {}

    for result in (
        vector_results +
        keyword_results
    ):

        document_id = result[
            "document_id"
        ]

        all_documents[
            document_id
        ] = result

    final_results = []

    for document_id, result in (
        all_documents.items()
    ):

        vector_score = vector_scores.get(
            document_id,
            0.0
        )

        keyword_score = keyword_scores.get(
            document_id,
            0.0
        )

        combined_score = (
            vector_weight *
            vector_score
            +
            keyword_weight *
            keyword_score
        )

        final_results.append({
            **result,
            "vector_score": vector_score,
            "keyword_score": keyword_score,
            "hybrid_score": combined_score
        })

    final_results.sort(
        key=lambda x: x["hybrid_score"],
        reverse=True
    )

    return final_results[:top_k]


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    question = (
        "What does REG-002 say "
        "about registration restrictions?"
    )

    results = hybrid_search(
        question,
        top_k=3
    )

    print("\nQUESTION:")
    print(question)

    print("\nHYBRID RESULTS:")

    for i, result in enumerate(
        results,
        start=1
    ):

        print("\n-------------------")
        print("Rank:", i)
        print("Document:", result["document_id"])
        print("Title:", result["title"])
        print(
            "Vector:",
            round(
                result["vector_score"],
                3
            )
        )
        print(
            "Keyword:",
            round(
                result["keyword_score"],
                3
            )
        )
        print(
            "Hybrid:",
            round(
                result["hybrid_score"],
                3
            )
        )