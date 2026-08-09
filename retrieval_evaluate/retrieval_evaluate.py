from pathlib import Path
import json
import time
import csv

from rag.naive_rag import retrieve
from rag.hybrid_rag import hybrid_search
from rag.agentic_rag import agentic_retrieve


# ============================================================
# PATH CONFIGURATION
# ============================================================

# Current folder:
# brightpeaktask3/retrieval_evaluate/

CURRENT_DIR = Path(__file__).resolve().parent

# Questions are in the SAME folder as this Python file
QUESTIONS_FILE = CURRENT_DIR / "retrieval_questions.json"

# Results will also be saved in the same folder
OUTPUT_FILE = CURRENT_DIR / "results.csv"


# ============================================================
# LOAD QUESTIONS
# ============================================================

def load_questions():

    if not QUESTIONS_FILE.exists():
        raise FileNotFoundError(
            f"\nQuestions file not found:\n{QUESTIONS_FILE}"
        )

    with open(
        QUESTIONS_FILE,
        "r",
        encoding="utf-8"
    ) as file:

        return json.load(file)


# ============================================================
# NORMALIZE RETRIEVAL RESULTS
# ============================================================

def normalize_result(result):
    """
    Convert retrieval results from different RAG architectures
    into one common structure.

    Supported keys:
        document_id / id
        text / content
    """

    document_id = (
        result.get("document_id")
        or result.get("id")
    )

    text = (
        result.get("text")
        or result.get("content")
        or ""
    )

    return {
        "document_id": document_id,
        "text": text
    }


# ============================================================
# EVALUATE RETRIEVAL ACCURACY
# ============================================================

def evaluate_results(
    results,
    expected_documents
):

    normalized_results = [
        normalize_result(result)
        for result in results
    ]

    retrieved_ids = {
        result["document_id"]
        for result in normalized_results
        if result["document_id"] is not None
    }

    expected_ids = set(expected_documents)

    if not expected_ids:
        return 0.0

    hits = retrieved_ids & expected_ids

    return len(hits) / len(expected_ids)


# ============================================================
# TOKEN ESTIMATION
# ============================================================

def estimate_tokens(text):

    # Simple reproducible token estimate.
    return max(
        1,
        len(text.split())
    )


# ============================================================
# RUN EVALUATION
# ============================================================

def run_evaluation():

    questions = load_questions()

    print(
        f"\nLoaded {len(questions)} evaluation questions."
    )

    rows = []

    architectures = [
        "naive",
        "hybrid",
        "agentic"
    ]

    for question in questions:

        question_id = question["id"]

        query = question["question"]

        expected = question[
            "expected_documents"
        ]

        print("\n" + "=" * 80)
        print(f"Question: {question_id}")
        print(query)
        print("=" * 80)

        for architecture in architectures:

            print(
                f"\nRunning {architecture}..."
            )

            start = time.perf_counter()

            # ------------------------------------------------
            # NAIVE RAG
            # ------------------------------------------------

            if architecture == "naive":

                raw_results = retrieve(
                    query,
                    top_k=3
                )

                trace = []

            # ------------------------------------------------
            # HYBRID RAG
            # ------------------------------------------------

            elif architecture == "hybrid":

                raw_results = hybrid_search(
                    query,
                    top_k=3
                )

                trace = []

            # ------------------------------------------------
            # AGENTIC RAG
            # ------------------------------------------------

            else:

                response = agentic_retrieve(
                    query,
                    top_k=3
                )

                raw_results = response.get(
                    "results",
                    []
                )

                trace = response.get(
                    "trace",
                    []
                )

            # ------------------------------------------------
            # NORMALIZE RESULTS
            # ------------------------------------------------

            results = [
                normalize_result(result)
                for result in raw_results
            ]

            # ------------------------------------------------
            # LATENCY
            # ------------------------------------------------

            latency = (
                time.perf_counter()
                - start
            )

            # ------------------------------------------------
            # ACCURACY
            # ------------------------------------------------

            accuracy = evaluate_results(
                results,
                expected
            )

            # ------------------------------------------------
            # RETRIEVED TEXT
            # ------------------------------------------------

            retrieved_text = " ".join(
                result["text"]
                for result in results
            )

            # ------------------------------------------------
            # TOKEN ESTIMATION
            # ------------------------------------------------

            tokens = estimate_tokens(
                query
                + " "
                + retrieved_text
            )

            # ------------------------------------------------
            # RETRIEVAL ROUNDS
            # ------------------------------------------------

            retrieval_rounds = max(
                1,
                len([
                    item
                    for item in trace
                    if isinstance(item, dict)
                    and item.get("action") == "retrieve"
                ])
            )

            # ------------------------------------------------
            # RETRIEVED DOCUMENT IDS
            # ------------------------------------------------

            retrieved_documents = ",".join(
                str(result["document_id"])
                for result in results
                if result["document_id"] is not None
            )

            # ------------------------------------------------
            # SAVE ROW
            # ------------------------------------------------

            rows.append({

                "question_id":
                    question_id,

                "architecture":
                    architecture,

                "accuracy":
                    round(
                        accuracy,
                        3
                    ),

                "tokens":
                    tokens,

                "latency_seconds":
                    round(
                        latency,
                        4
                    ),

                "expected_architecture":
                    question.get(
                        "expected_architecture",
                        ""
                    ),

                "retrieved_documents":
                    retrieved_documents,

                "retrieval_rounds":
                    retrieval_rounds
            })

            print(
                f"Accuracy: {accuracy:.3f} | "
                f"Latency: {latency:.4f}s | "
                f"Tokens: {tokens}"
            )

    return rows


# ============================================================
# SAVE RESULTS
# ============================================================

def save_results(rows):

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    fieldnames = [
        "question_id",
        "architecture",
        "accuracy",
        "tokens",
        "latency_seconds",
        "expected_architecture",
        "retrieved_documents",
        "retrieval_rounds"
    ]

    with open(
        OUTPUT_FILE,
        "w",
        newline="",
        encoding="utf-8"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames
        )

        writer.writeheader()

        writer.writerows(rows)

    print(
        "\nDetailed results saved to:"
    )

    print(OUTPUT_FILE)


# ============================================================
# PRINT SUMMARY
# ============================================================

def print_summary(rows):

    print("\n")
    print("=" * 80)
    print("RETRIEVAL COMPARISON")
    print("=" * 80)

    for architecture in [
        "naive",
        "hybrid",
        "agentic"
    ]:

        architecture_rows = [
            row
            for row in rows
            if row["architecture"]
            == architecture
        ]

        if not architecture_rows:
            continue

        avg_accuracy = (
            sum(
                row["accuracy"]
                for row in architecture_rows
            )
            /
            len(architecture_rows)
        )

        avg_tokens = (
            sum(
                row["tokens"]
                for row in architecture_rows
            )
            /
            len(architecture_rows)
        )

        avg_latency = (
            sum(
                row["latency_seconds"]
                for row in architecture_rows
            )
            /
            len(architecture_rows)
        )

        avg_rounds = (
            sum(
                row["retrieval_rounds"]
                for row in architecture_rows
            )
            /
            len(architecture_rows)
        )

        print(
            f"{architecture:10} | "
            f"Accuracy: {avg_accuracy:.3f} | "
            f"Tokens: {avg_tokens:.1f} | "
            f"Latency: {avg_latency:.4f}s | "
            f"Rounds: {avg_rounds:.1f}"
        )

    print("=" * 80)


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    results = run_evaluation()

    save_results(results)

    print_summary(results)

    print(
        "\nEvaluation completed successfully."
    )