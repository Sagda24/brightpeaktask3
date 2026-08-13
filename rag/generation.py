def build_rag_prompt(
    question,
    retrieved_results
):

    context = "\n\n".join(
        [
            (
                f"Source: {result['title']}\n"
                f"Document ID: {result['document_id']}\n"
                f"Content: {result['text']}"
            )
            for result in retrieved_results
        ]
    )

    prompt = f"""
You are the BrightPeak Academy assistant.

Answer the user's question using ONLY the
retrieved knowledge below.

If the retrieved knowledge does not contain
enough information, explicitly say that the
available knowledge base does not provide
enough information.

Do not invent policies.

Retrieved Knowledge:
--------------------
{context}
--------------------

Question:
{question}

Provide a concise answer and mention the
relevant policy/source when possible.
"""

    return prompt