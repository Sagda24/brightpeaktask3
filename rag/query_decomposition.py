DECOMPOSE_PROMPT = """\
Break the following question into 2-4 simpler sub-questions that, together,
fully answer it. If the question is already simple, just return it as-is
as a single sub-question.

Question: {query}

Return ONLY a numbered list, one sub-question per line. Example:
1. ...
2. ...
"""


def parse_sub_questions(raw: str) -> list:
    """Parse an LLM's numbered-list response into a clean list of
    sub-question strings. Tolerant of "1.", "1)", "- " and similar
    leading markers, and of blank lines / stray whitespace."""
    sub_questions = []
    for line in (raw or "").strip().splitlines():
        line = line.strip()
        if not line:
            continue
        for sep in [". ", ") ", "- "]:
            if sep in line[:4]:
                line = line.split(sep, 1)[1]
                break
        line = line.strip()
        if line:
            sub_questions.append(line)
    return sub_questions
