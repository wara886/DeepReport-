"""Reranker adapter for Hybrid RAG candidate lists."""

from __future__ import annotations

from typing import Any

from src.training.infer_reranker import rerank_hits_with_meta


class RerankerAdapter:
    def __init__(self, *, checkpoint_path: str = "data/outputs/checkpoints/reranker_checkpoint.json") -> None:
        self.checkpoint_path = checkpoint_path

    def rerank(self, *, query: str, hits: list[dict[str, Any]], topk: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        try:
            ranked, meta = rerank_hits_with_meta(hits=hits, query=query, checkpoint_path=self.checkpoint_path)
            return ranked[:topk], dict(meta, available=True)
        except Exception as exc:  # noqa: BLE001 - retrieval should preserve candidates.
            return hits[:topk], {"available": False, "fallback_used": True, "error": str(exc), "checkpoint_used": False}
