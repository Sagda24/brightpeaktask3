import json
import time
import csv

from rag.naive_rag import retrieve
from rag.hybrid_rag import hybrid_search
from rag.agentic_rag import agentic_retrieve


QUESTIONS_FILE = (
    "retrieval_eval/questions.json"
)


def load_questions():

    with open(
        QUESTIONS_FILE,
        "r",
        encoding="utf-8"
    ) as file:

        return json.load(file)


def evaluate_results(
    results,
    expected_documents
):

    retrieved_ids = {
        result["document_id"]
        for result in results
    }

    expected_ids = set(
        expected_documents
    )

    if not expected_ids:
        return 0.0

    hits = (
        retrieved_ids
        &
        expected_ids
    )

    return len(hits) / len(
        expected_ids
    )


def estimate_tokens(text):

    # Simple reproducible estimate.
    return max(
        1,
        len(text.split())
    )


def run_evaluation():

    questions = load_questions()

    rows = []

    architectures = [
        "naive",
        "hybrid",
        "agentic"
    ]

    for question in questions:

        query = question["question"]

        expected = question[
            "expected_documents"
        ]

        for architecture in architectures:

            start = time.perf_counter()

            if architecture == "naive":

                results = retrieve(
                    query,
                    top_k=3
                )

                trace = []

            elif architecture == "hybrid":

                results = hybrid_search(
                    query,
                    top_k=3
                )

                trace = []

            else:

                response = agentic_retrieve(
                    query,
                    top_k=3
                )

                results = response[
                    "results"
                ]

                trace = response[
                    "trace"
                ]

            latency = (
                time.perf_counter()
                - start
            )

            accuracy = evaluate_results(
                results,
                expected
            )

            retrieved_text = " ".join(
                result["text"]
                for result in results
            )

            tokens = estimate_tokens(
                query
                + " "
                + retrieved_text
            )

            rows.append({
                "question_id": question["id"],
                "architecture": architecture,
                "accuracy": round(
                    accuracy,
                    3
                ),
                "tokens": tokens,
                "latency_seconds": round(
                    latency,
                    4
                ),
                "expected_architecture":
                    question[
                        "expected_architecture"
                    ],
                "retrieved_documents":
                    ",".join(
                        result[
                            "document_id"
                        ]
                        for result in results
                    ),
                "retrieval_rounds":
                    max(
                        1,
                        len([
                            item
                            for item in trace
                            if item.get(
                                "action"
                            ) == "retrieve"
                        ])
                    )
            })

    return rows


def save_results(rows):

    output_file = (
        "retrieval_eval/results.csv"
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
        output_file,
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


def print_summary(rows):

    print("\nRETRIEVAL COMPARISON")
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

        print(
            f"{architecture:10} | "
            f"Accuracy: {avg_accuracy:.3f} | "
            f"Tokens: {avg_tokens:.1f} | "
            f"Latency: {avg_latency:.4f}s"
        )


if __name__ == "__main__":

    results = run_evaluation()

    save_results(results)

    print_summary(results)

    print(
        "\nDetailed results saved to "
        "retrieval_eval/results.csv"
    )