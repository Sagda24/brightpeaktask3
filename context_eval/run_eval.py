import json
import os
from collections import defaultdict

from .transcripts import build_test_suite
from .strategies import ALL_STRATEGIES
from .agent import run_strategy_on_transcript

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")


def run_all():
    suite = build_test_suite()
    raw_results = []

    for strategy in ALL_STRATEGIES:
        for transcript in suite:
            raw_results.append(run_strategy_on_transcript(strategy, transcript))

    return raw_results


def aggregate(raw_results):
    by_strategy = defaultdict(list)
    for r in raw_results:
        by_strategy[r["strategy"]].append(r)

    table = []
    for strategy_name, runs in by_strategy.items():
        n = len(runs)
        correct = sum(1 for r in runs if r["correct"])
        avg_input = sum(r["input_tokens"] for r in runs) / n
        avg_output = sum(r["output_tokens"] for r in runs) / n
        avg_latency = sum(r["latency_s"] for r in runs) / n
        table.append({
            "strategy": strategy_name,
            "accuracy": f"{correct}/{n}",
            "accuracy_frac": correct / n,
            "avg_input_tokens": round(avg_input),
            "avg_output_tokens": round(avg_output),
            "avg_latency_s": round(avg_latency, 2),
        })

    # stable order matching the lab's own table (sliding, masking, summary, zone)
    order = ["sliding_window", "observation_masking", "recursive_summarization", "zone_based_pruning"]
    table.sort(key=lambda row: order.index(row["strategy"]))
    return table


def render_markdown_table(table):
    lines = [
        "| Strategy | Critical fact recalled correctly | Avg. input tokens/run | Avg. output tokens/run | Avg. latency |",
        "|---|---|---|---|---|",
    ]
    pretty_names = {
        "sliding_window": "Sliding window (last 10 turns)",
        "observation_masking": "Observation/tool-output masking (keep last 3)",
        "recursive_summarization": "Recursive summarization (compact every 15 turns)",
        "zone_based_pruning": "Zone-based pruning (4 zones)",
    }
    for row in table:
        lines.append(
            f"| {pretty_names[row['strategy']]} | {row['accuracy']} | "
            f"{row['avg_input_tokens']:,} | {row['avg_output_tokens']} | {row['avg_latency_s']}s |"
        )
    return "\n".join(lines)


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    raw_results = run_all()
    table = aggregate(raw_results)
    md_table = render_markdown_table(table)

    with open(os.path.join(RESULTS_DIR, "raw_results.json"), "w") as f:
        json.dump(raw_results, f, indent=2)

    with open(os.path.join(RESULTS_DIR, "comparison_table.md"), "w") as f:
        f.write("# Context Management Strategy Comparison\n\n")
        f.write("10-transcript BrightPeak advising-call long-context test suite "
                "(see transcripts.py). Each transcript buries one critical "
                "eligibility fact (a prerequisite waiver, a cleared registration "
                "hold, a credit-overload exception, or approved transfer credit) "
                "under 28-40 turns of tool-heavy noise, then asks the agent to "
                "account for it on the final turn.\n\n")
        f.write(md_table + "\n")

    print(md_table)
    print(f"\nWrote {RESULTS_DIR}/comparison_table.md and raw_results.json")
    return table


if __name__ == "__main__":
    main()
