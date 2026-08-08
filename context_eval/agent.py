from .metrics import score_run


def answer_final_question(pruned_turns: list, critical_marker: str) -> dict:
    context_text = "\n".join(t.get("content", "") for t in pruned_turns).lower()
    found = critical_marker.lower() in context_text

    if found:
        answer = f"Yes -- on file: \"{critical_marker}\". Proceeding accordingly."
    else:
        answer = "I don't see anything on file about that -- proceeding without it."

    return {"answer": answer, "correct": found}


def run_strategy_on_transcript(strategy, transcript: dict) -> dict:
    result = strategy.apply(transcript["turns"])
    pruned_turns = result["pruned_turns"]

    answer = answer_final_question(pruned_turns, transcript["critical_marker"])
    cost = score_run(pruned_turns, result["extra_output_tokens"], result["extra_llm_calls"])

    return {
        "transcript_id": transcript["id"],
        "fact_type": transcript["fact_type"],
        "strategy": strategy.name,
        "correct": answer["correct"],
        "answer": answer["answer"],
        "notes": result["notes"],
        **cost,
    }
