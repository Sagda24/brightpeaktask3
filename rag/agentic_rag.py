from rag.naive_rag import retrieve
from rag.hybrid_rag import hybrid_search


def needs_second_retrieval(
    query,
    first_results
):
    """
    Decide whether the first retrieval
    is insufficient.

    This is intentionally explicit so
    the decision is visible during demo.
    """

    if not first_results:
        return True

    combined_text = " ".join(
        result["text"]
        for result in first_results
    ).lower()

    query_terms = [
        word.lower()
        for word in query.split()
        if len(word) > 3
    ]

    matched_terms = sum(
        1
        for term in query_terms
        if term in combined_text
    )

    coverage = (
        matched_terms
        /
        max(len(query_terms), 1)
    )

    return coverage < 0.5


def build_second_query(query):

    return (
        f"{query} "
        "provide all relevant academic policy "
        "requirements and related restrictions"
    )


def agentic_retrieve(
    query,
    top_k=3,
    max_rounds=2
):

    trace = []

    # --------------------------------------------------------
    # ROUND 1
    # --------------------------------------------------------

    first_results = retrieve(
        query,
        top_k=top_k
    )

    trace.append({
        "round": 1,
        "query": query,
        "action": "retrieve",
        "result_count": len(first_results)
    })

    # --------------------------------------------------------
    # OBSERVE
    # --------------------------------------------------------

    needs_more = needs_second_retrieval(
        query,
        first_results
    )

    trace.append({
        "round": 1,
        "action": "observe",
        "needs_more_retrieval": needs_more
    })

    # --------------------------------------------------------
    # DECIDE
    # --------------------------------------------------------

    if not needs_more:

        return {
            "results": first_results,
            "trace": trace
        }

    # --------------------------------------------------------
    # ROUND 2
    # --------------------------------------------------------

    if max_rounds < 2:

        return {
            "results": first_results,
            "trace": trace
        }

    second_query = build_second_query(
        query
    )

    second_results = hybrid_search(
        second_query,
        top_k=top_k
    )

    trace.append({
        "round": 2,
        "query": second_query,
        "action": "retrieve",
        "result_count": len(second_results)
    })

    # --------------------------------------------------------
    # MERGE RESULTS
    # --------------------------------------------------------

    combined = {}

    for result in (
        first_results +
        second_results
    ):

        document_id = result[
            "document_id"
        ]

        combined[
            document_id
        ] = result

    final_results = list(
        combined.values()
    )[:top_k]

    trace.append({
        "round": 2,
        "action": "observe",
        "message": "Results from second retrieval merged."
    })

    return {
        "results": final_results,
        "trace": trace
    }


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    question = (
        "What are the requirements for "
        "course registration and what happens "
        "if a student has restrictions?"
    )

    response = agentic_retrieve(
        question
    )

    print("\nQUESTION:")
    print(question)

    print("\nAGENT TRACE:")

    for step in response["trace"]:
        print(step)

    print("\nFINAL RESULTS:")

    for result in response["results"]:

        print("\n-------------------")
        print(result["document_id"])
        print(result["title"])
        print(result["text"])