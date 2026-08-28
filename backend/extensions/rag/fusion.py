from __future__ import annotations


def reciprocal_rank_fusion(
    ranked_lists: list[list[int]],
    k: int = 60,
) -> dict[int, float]:
    """
    Fusionne plusieurs classements (listes d'ids, meilleur en premier) en un
    score unique par id — Reciprocal Rank Fusion : score = somme(1 / (k + rang)).

    rang commence à 1. Un id absent d'une liste ne contribue pas pour celle-ci.
    """
    scores: dict[int, float] = {}
    for ranked in ranked_lists:
        for rank, item_id in enumerate(ranked, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
    return scores
