"""Reciprocal rank fusion utilities for hybrid retrieval."""

from __future__ import annotations

from typing import Any


def reciprocal_rank_fusion(
    ranked_lists: list[list[dict[str, Any]]],
    *,
    topk: int = 10,
    k: int = 60,
    id_field: str = "evidence_id",
) -> list[dict[str, Any]]:
    """Fuse ranked hit lists with RRF while preserving component scores."""

    fused: dict[str, dict[str, Any]] = {}
    for list_index, hits in enumerate(ranked_lists):
        component = _component_name(list_index)
        for rank, hit in enumerate(hits, start=1):
            hit_id = _hit_id(hit, id_field=id_field)
            score = 1.0 / (k + rank)
            if hit_id not in fused:
                fused[hit_id] = dict(hit)
                fused[hit_id]["rrf_score"] = 0.0
                fused[hit_id]["rank_sources"] = []
                fused[hit_id]["component_ranks"] = {}
            fused[hit_id]["rrf_score"] = float(fused[hit_id].get("rrf_score", 0.0)) + score
            fused[hit_id]["rank_sources"].append(component)
            fused[hit_id]["component_ranks"][component] = rank
            for key in ("bm25_score", "vector_score", "graph_score", "rerank_score"):
                if key in hit and fused[hit_id].get(key) is None:
                    fused[hit_id][key] = hit.get(key)

    ranked = sorted(fused.values(), key=lambda item: (float(item.get("rrf_score", 0.0)), float(item.get("score", 0.0) or 0.0)), reverse=True)
    for item in ranked:
        item["final_score"] = float(item.get("rrf_score", 0.0))
    return ranked[: max(0, int(topk or 0))]


def _hit_id(hit: dict[str, Any], *, id_field: str) -> str:
    for key in ("identity_key", id_field, "sample_id", "chunk_id", "id", "source_url"):
        value = hit.get(key)
        if value not in (None, ""):
            return str(value)
    return str(abs(hash(str(sorted(hit.items())))))


def _component_name(index: int) -> str:
    return ["bm25", "dense", "graph", "reranker"][index] if index < 4 else f"component_{index}"
