"""
Evaluates the self-correction layer (self_correction/) the same way
retrieval_evaluate/retrieval_evaluate.py and planning_evaluation/ evaluate
their own layers: one fixed test set, every configuration run against the
same cases, results written to disk.

Configurations compared, 2x2:
    algorithm:  Self-Refine  vs  Reflexion
    feedback:   grounded     vs  ungrounded   (self_correction/environment.py)

Metrics (per configuration, averaged over the fixed test set in
test_cases.json):
    - accuracy         : fraction of cases whose FINAL candidate actually
                          matches the real, grounded ground truth (checked
                          independently of which environment produced it --
                          an ungrounded run can "converge" while still
                          being wrong, which is exactly what this metric
                          is meant to expose)
    - avg_iterations    : mean self-refine iterations / reflexion trials
    - avg_llm_calls     : mean LLM calls per case
    - avg_tokens        : mean total tokens per case
    - avg_latency_ms    : mean wall-clock time per case

Run it:
    python -m self_correction_evaluation.evaluate_self_correction
"""
from __future__ import annotations

import csv
import json
import os
import time

from planning.db_tools import TOOL_REGISTRY
from self_correction.environment import Environment, GroundedEnvironment
from self_correction.self_refine import SelfRefine
from self_correction.reflexion import Reflexion, ReflexionMemory
from self_correction_evaluation.eval_mock_llm import GeneralMockLLM

HERE = os.path.dirname(__file__)


def load_test_cases() -> list:
    with open(os.path.join(HERE, "test_cases.json")) as f:
        return json.load(f)


def ground_truth_matches(task: dict, candidate: dict) -> bool:
    """Independent correctness check -- reuses GroundedEnvironment's own
    comparison logic (no LLM call) so 'accuracy' means the same thing
    whichever environment actually produced the candidate."""
    return GroundedEnvironment.is_correct(task, candidate)


def run_self_refine(task: dict, grounded: bool):
    llm = GeneralMockLLM()
    env = GroundedEnvironment(llm) if grounded else Environment(llm)
    t0 = time.perf_counter()
    result = SelfRefine(llm, env, max_iterations=3).run(task)
    latency_ms = (time.perf_counter() - t0) * 1000
    return {
        "correct": ground_truth_matches(task, result.final_candidate),
        "iterations": result.iterations,
        "llm_calls": result.llm_calls,
        "tokens": result.total_tokens,
        "latency_ms": latency_ms,
    }


def run_reflexion(task: dict, grounded: bool):
    llm = GeneralMockLLM()
    env = GroundedEnvironment(llm) if grounded else Environment(llm)
    t0 = time.perf_counter()
    result = Reflexion(llm, env, memory=ReflexionMemory(), max_trials=3).run(task, task_key=task["tool"])
    latency_ms = (time.perf_counter() - t0) * 1000
    return {
        "correct": ground_truth_matches(task, result.final_candidate),
        "iterations": len(result.trials),
        "llm_calls": result.llm_calls,
        "tokens": result.total_tokens,
        "latency_ms": latency_ms,
    }


def summarize(rows: list) -> dict:
    n = len(rows)
    return {
        "accuracy": sum(r["correct"] for r in rows) / n,
        "avg_iterations": sum(r["iterations"] for r in rows) / n,
        "avg_llm_calls": sum(r["llm_calls"] for r in rows) / n,
        "avg_tokens": sum(r["tokens"] for r in rows) / n,
        "avg_latency_ms": sum(r["latency_ms"] for r in rows) / n,
    }


def main():
    cases = load_test_cases()
    configs = [
        ("Self-Refine", "grounded", run_self_refine, True),
        ("Self-Refine", "ungrounded", run_self_refine, False),
        ("Reflexion", "grounded", run_reflexion, True),
        ("Reflexion", "ungrounded", run_reflexion, False),
    ]

    all_results = {}
    detail = []
    for algo_name, feedback_name, run_fn, grounded in configs:
        rows = []
        for case in cases:
            r = run_fn(case, grounded)
            r["case_id"] = case["case_id"]
            detail.append({"algorithm": algo_name, "feedback": feedback_name, **r})
            rows.append(r)
        all_results[f"{algo_name} / {feedback_name}"] = summarize(rows)

    out_json = os.path.join(HERE, "results.json")
    with open(out_json, "w") as f:
        json.dump({"summary": all_results, "detail": detail}, f, indent=2)

    out_csv = os.path.join(HERE, "results.csv")
    with open(out_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Configuration", "Accuracy", "Avg Iterations", "Avg LLM Calls", "Avg Tokens", "Avg Latency (ms)"])
        for name, s in all_results.items():
            writer.writerow([
                name,
                f"{s['accuracy']:.2f}",
                f"{s['avg_iterations']:.2f}",
                f"{s['avg_llm_calls']:.2f}",
                f"{s['avg_tokens']:.1f}",
                f"{s['avg_latency_ms']:.2f}",
            ])

    print(f"{'Configuration':<26}{'Accuracy':>10}{'Iter':>8}{'LLM calls':>12}{'Tokens':>10}{'Latency(ms)':>14}")
    for name, s in all_results.items():
        print(f"{name:<26}{s['accuracy']:>10.2f}{s['avg_iterations']:>8.2f}"
              f"{s['avg_llm_calls']:>12.2f}{s['avg_tokens']:>10.1f}{s['avg_latency_ms']:>14.2f}")
    print(f"\nWritten to {out_json} and {out_csv}")


if __name__ == "__main__":
    main()
