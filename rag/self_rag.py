import re


# ============================================================
# TEXT UTILITIES
# ============================================================

def normalize_text(text):

    text = text.lower()

    text = re.sub(
        r"[^a-z0-9\s%\-]",
        " ",
        text
    )

    return text


def extract_terms(text):

    words = normalize_text(
        text
    ).split()

    stop_words = {
        "what",
        "does",
        "the",
        "is",
        "are",
        "for",
        "and",
        "how",
        "can",
        "with",
        "this",
        "that",
        "from",
        "student",
        "students"
    }

    return {
        word
        for word in words
        if len(word) > 3
        and word not in stop_words
    }


# ============================================================
# POST-RETRIEVAL RELEVANCE CHECK
# ============================================================

def check_retrieval_relevance(
    query,
    results,
    minimum_relevance=0.15
):

    if not results:

        return {
            "passed": False,
            "reason": "No retrieved content."
        }

    query_terms = extract_terms(
        query
    )

    best_overlap = 0.0
    best_result = None

    for result in results:

        result_terms = extract_terms(
            result["text"]
        )

        if not query_terms:
            overlap = 0.0

        else:

            overlap = (
                len(
                    query_terms
                    &
                    result_terms
                )
                /
                len(query_terms)
            )

        if overlap > best_overlap:

            best_overlap = overlap
            best_result = result

    passed = (
        best_overlap >=
        minimum_relevance
    )

    return {
        "passed": passed,
        "score": best_overlap,
        "best_document": (
            best_result["document_id"]
            if best_result
            else None
        ),
        "reason": (
            "Retrieved content is relevant."
            if passed
            else
            "Retrieved content is not sufficiently relevant."
        )
    }


# ============================================================
# POST-GENERATION SUPPORT CHECK
# ============================================================

def check_answer_support(
    answer,
    retrieved_results,
    minimum_support=0.15
):

    if not answer:

        return {
            "passed": False,
            "score": 0.0,
            "reason": "Empty answer."
        }

    context = " ".join(
        result["text"]
        for result in retrieved_results
    )

    answer_terms = extract_terms(
        answer
    )

    context_terms = extract_terms(
        context
    )

    if not answer_terms:

        support_score = 0.0

    else:

        support_score = (
            len(
                answer_terms
                &
                context_terms
            )
            /
            len(answer_terms)
        )

    passed = (
        support_score >=
        minimum_support
    )

    return {
        "passed": passed,
        "score": support_score,
        "reason": (
            "Answer is supported by retrieved evidence."
            if passed
            else
            "Answer contains claims not sufficiently supported by retrieved evidence."
        )
    }


# ============================================================
# SELF-RAG DECISION
# ============================================================

def self_rag_verify(
    query,
    retrieved_results,
    answer
):

    relevance = check_retrieval_relevance(
        query,
        retrieved_results
    )

    if not relevance["passed"]:

        return {
            "approved": False,
            "action": "RETRIEVE_AGAIN",
            "retrieval_check": relevance,
            "generation_check": None
        }

    support = check_answer_support(
        answer,
        retrieved_results
    )

    if not support["passed"]:

        return {
            "approved": False,
            "action": "REGENERATE_OR_RETRIEVE",
            "retrieval_check": relevance,
            "generation_check": support
        }

    return {
        "approved": True,
        "action": "RETURN_ANSWER",
        "retrieval_check": relevance,
        "generation_check": support
    }
