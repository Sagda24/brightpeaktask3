from dataclasses import dataclass


DECOMPOSE_PROMPT = """\
Break the following question into 2-4 simpler sub-questions that, together,
fully answer it.

If the question is already simple, return it as-is as a single sub-question.

Question:
{query}

Return ONLY a numbered list, one sub-question per line.

Example:
1. What are the attendance requirements?
2. What happens if attendance is below the requirement?
"""


class MCPModelAdapter:

    def __init__(self, ctx):
        self.ctx = ctx

    async def complete(self, prompt: str) -> str:

        response = await self.ctx.sample(
            messages=prompt,
            max_tokens=300
        )

        return response.text


async def decompose_query(
    query: str,
    llm
) -> list[str]:

    raw = await llm.complete(
        DECOMPOSE_PROMPT.format(query=query)
    )

    sub_questions = []

    for line in raw.strip().splitlines():

        line = line.strip()

        if not line:
            continue

        # Remove numbering
        if len(line) >= 3:
            if line[0].isdigit() and line[1:3] in [". ", ") "]:
                line = line[3:]

        if line.startswith("- "):
            line = line[2:]

        if line.strip():
            sub_questions.append(
                line.strip()
            )

    return sub_questions or [query]


@dataclass
class TaggedChunk:

    sub_question: str
    chunk: str
    score: float


async def combine_search(
    query: str,
    search_tool,
    ctx,
    top_k: int = 3
):

    # --------------------------------
    # 1. Use the SAME project LLM
    # --------------------------------

    llm = MCPModelAdapter(ctx)

    # --------------------------------
    # 2. Decompose original question
    # --------------------------------

    sub_questions = await decompose_query(
        query,
        llm
    )

    results = []

    # --------------------------------
    # 3. Search every sub-question
    # --------------------------------

    for sub_question in sub_questions:

        search_result = search_tool(
            sub_question,
            top_k
        )

        # Existing MCP search returns:
        #
        # {
        #   "status": "success",
        #   "results": [...]
        # }

        hits = search_result.get(
            "results",
            []
        )

        # --------------------------------
        # 4. Tag every retrieved chunk
        # --------------------------------

        for hit in hits:

            results.append(
                TaggedChunk(
                    sub_question=sub_question,
                    chunk=hit.get(
                        "content",
                        ""
                    ),
                    score=float(
                        hit.get(
                            "score",
                            0
                        )
                    )
                )
            )

    return results