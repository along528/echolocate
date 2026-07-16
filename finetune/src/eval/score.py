"""
Retrieval metrics for the fine-tuning eval: NDCG@10, recall@10, judged@10 coverage.

Graded relevance (`gain` in {0,1,2}) comes from the frozen qrels (src/eval/build_qrels.py).
DCG uses the standard exponential gain (2^gain - 1) with a log2(rank+2) discount. Unjudged
tracks in a ranking contribute gain 0 (standard "unjudged = non-relevant" assumption; its
risk is quantified by the judged@k coverage metric).

These functions are ranker-agnostic: pass a ranked list of track_ids and the query's qrel map.
"""

from __future__ import annotations

import math

K = 10


def _dcg(gains: list[int]) -> float:
    return sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(gains))


def ndcg_at_k(ranked_ids: list[str], qrel: dict[str, int], k: int = K) -> float:
    """NDCG@k. `qrel` maps track_id -> gain for this query (judged tracks only)."""
    gains = [qrel.get(tid, 0) for tid in ranked_ids[:k]]
    dcg = _dcg(gains)
    ideal = _dcg(sorted(qrel.values(), reverse=True)[:k])
    if ideal == 0.0:
        return 0.0
    return dcg / ideal


def recall_at_k(ranked_ids: list[str], qrel: dict[str, int], k: int = K) -> float:
    """
    Recall@k over binary-positive judged tracks (gain > 0 == relevant or borderline).
    Denominator is the number of positives *known for this query* (judged pool), so this is
    recall within the seed judgments, not absolute recall.
    """
    positives = {tid for tid, g in qrel.items() if g > 0}
    if not positives:
        return 0.0
    hit = sum(1 for tid in ranked_ids[:k] if tid in positives)
    return hit / len(positives)


def judged_coverage_at_k(ranked_ids: list[str], qrel: dict[str, int], k: int = K) -> float:
    """Fraction of the top-k that carry a judgment — trustworthiness of NDCG@k for this query."""
    top = ranked_ids[:k]
    if not top:
        return 0.0
    return sum(1 for tid in top if tid in qrel) / len(top)
