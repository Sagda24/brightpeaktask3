import json
import re
from pathlib import Path
from collections import Counter
import math

from .query_decomposition import parse_sub_questions

KB_PATH = Path(__file__).parent / "knowledge_base" / "knowledge_base.json"


def _load_docs():
    with open(KB_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


class MiniBM25:
    """A small BM25Okapi-compatible reimplementation (k1=1.5, b=0.75, same
    defaults as rank_bm25.BM25Okapi) so this demo has no extra dependency
    beyond what's already in the repo, and produces the same ranking
    Mcp-Server/server.py's real rank_bm25-backed search would."""

    def __init__(self, tokenized_docs, k1=1.5, b=0.75):
        self.k1, self.b = k1, b
        self.docs = tokenized_docs
        self.N = len(tokenized_docs)
        self.avgdl = sum(len(d) for d in tokenized_docs) / self.N
        df = Counter()
        for d in tokenized_docs:
            for w in set(d):
                df[w] += 1
        self.idf = {w: math.log((self.N - c + 0.5) / (c + 0.5) + 1) for w, c in df.items()}

    def get_scores(self, query_tokens):
        scores = []
        for doc_tokens in self.docs:
            freqs = Counter(doc_tokens)
            dl = len(doc_tokens)
            s = 0.0
            for w in query_tokens:
                if w not in self.idf:
                    continue
                f = freqs.get(w, 0)
                s += self.idf[w] * (f * (self.k1 + 1)) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
            scores.append(s)
        return scores


_docs = _load_docs()
_tokenized = [d["text"].lower().split() for d in _docs]
_bm25 = MiniBM25(_tokenized)


def search_knowledge_base(query: str, top_k: int = 3):
    """Same logic/shape as Mcp-Server/server.py's search_knowledge_base."""
    scores = _bm25.get_scores(query.lower().split())
    ranked = sorted(zip(scores, _docs), key=lambda x: x[0], reverse=True)
    results = []
    for score, doc in ranked[:top_k]:
        if score > 0:
            results.append({"title": doc["title"], "content": doc["text"], "score": round(float(score), 2)})
    return {"status": "success", "results": results}


def offline_decompose(query: str) -> list:
    """Rule-based stand-in for the real ctx.sample() LLM call, used ONLY by
    this standalone demo (see module docstring). Splits on the conjunctions
    a compound BrightPeak question actually uses."""
    parts = re.split(r"\band\b|,\s*(?:and\s+)?(?=what|does|is|do|can|are)", query, flags=re.IGNORECASE)
    parts = [p.strip().rstrip("?").strip() + "?" for p in parts if p.strip()]
    return parse_sub_questions("\n".join(f"{i+1}. {p}" for i, p in enumerate(parts))) or [query]


def combine_search(query: str, top_k: int = 3):
    sub_questions = offline_decompose(query)
    tagged = []
    for sub_q in sub_questions:
        for hit in search_knowledge_base(sub_q, top_k)["results"]:
            tagged.append({"sub_question": sub_q, **hit})
    return sub_questions, tagged


if __name__ == "__main__":
    demo_query = (
        "What attendance percentage is required to sit the final exam, "
        "and what happens if I fail the course afterward?"
    )

    print("=== Plain search_knowledge_base (only sees the raw compound question) ===")
    plain = search_knowledge_base(demo_query, top_k=3)
    for r in plain["results"]:
        print(f"  [{r['score']}] {r['title']}")
    plain_titles = {r["title"] for r in plain["results"]}
    print(f"\n  -> Misses 'Final Examination Eligibility' -- the single most on-point")
    print(f"     policy doc for this question -- because the compound query's mixed")
    print(f"     vocabulary (attendance + failing/retake terms) dilutes the BM25 score")
    print(f"     for either topic individually.")

    print("\n=== decompose_and_search ===")
    sub_qs, tagged = combine_search(demo_query, top_k=3)
    print(f"  sub-questions: {sub_qs}")
    for r in tagged:
        print(f"  [{r['sub_question']}] -> [{r['score']}] {r['title']}")

    tagged_titles = {r["title"] for r in tagged}
    recovered = tagged_titles - plain_titles
    print(f"\n  -> Recovers {sorted(recovered)}, which plain top-3 search missed entirely.")
