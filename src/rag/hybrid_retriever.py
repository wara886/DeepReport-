"""Hybrid RAG retriever composed from BM25, dense, graph, RRF, and reranker."""

from __future__ import annotations

from typing import Any

from src.rag.bm25_retriever import BM25Retriever
from src.rag.dense_retriever import DenseRetriever
from src.rag.graph_retriever import GraphRetriever
from src.rag.reranker_adapter import RerankerAdapter
from src.rag.rrf_fusion import reciprocal_rank_fusion
from src.retrieval.chunking import chunk_records
from src.retrieval.evidence_store import EvidenceStore


class HybridRetriever:
    """Contract-first hybrid retriever used by the workbench and legacy wrapper."""

    def __init__(
        self,
        *,
        curated_dir: str = "data/curated",
        dense_retriever_cls: Any = DenseRetriever,
        graph_retriever_cls: Any = GraphRetriever,
        reranker: RerankerAdapter | None = None,
    ) -> None:
        self.curated_dir = curated_dir
        self.dense_retriever_cls = dense_retriever_cls
        self.graph_retriever_cls = graph_retriever_cls
        self.reranker = reranker

    def search(
        self,
        query: str,
        *,
        topk: int = 10,
        symbol: str | None = None,
        period: str | None = None,
        mode: str = "hybrid",
        use_chunks: bool = False,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        store = EvidenceStore.from_curated_parquet(curated_dir=self.curated_dir)
        store_meta = dict(getattr(store, "load_meta", {}) or {})
        records = store.filter(symbol=symbol, period=period)
        source_record_count = len(records)
        if use_chunks:
            records = chunk_records(records)
        record_count = len(records)
        mode = str(mode or "hybrid").strip().lower()
        candidate_topk = max(topk * 2, topk, 1)

        bm25_hits, bm25_meta = BM25Retriever(records).search(query, topk=candidate_topk)
        dense_hits: list[dict[str, Any]] = []
        graph_hits: list[dict[str, Any]] = []
        dense_meta: dict[str, Any] = {"backend": "disabled", "available": False, "hit_count": 0}
        graph_meta: dict[str, Any] = {"backend": "disabled", "available": False, "hit_count": 0}

        if mode in {"dense", "vector", "hybrid", "hybrid_rerank"}:
            dense_hits, dense_meta = self.dense_retriever_cls(records).search(query, topk=candidate_topk)
        if mode in {"graph", "hybrid", "hybrid_rerank"}:
            graph_hits, graph_meta = self.graph_retriever_cls(records).search(query, topk=candidate_topk)

        if mode in {"dense", "vector"}:
            fused = dense_hits
            mode_effective = "dense" if dense_hits else "bm25"
            if not fused:
                fused = bm25_hits
        elif mode == "graph":
            fused = graph_hits or bm25_hits
            mode_effective = "graph" if graph_hits else "bm25"
        else:
            fused = reciprocal_rank_fusion([bm25_hits, dense_hits, graph_hits], topk=candidate_topk)
            mode_effective = "hybrid" if (dense_hits or graph_hits) else "bm25"

        rerank_meta: dict[str, Any] = {"available": False, "checkpoint_used": False}
        if mode == "hybrid_rerank" and self.reranker is not None:
            fused, rerank_meta = self.reranker.rerank(query=query, hits=fused, topk=topk)

        returned = fused[:topk]
        for item in returned:
            item.setdefault("bm25_score", None)
            item.setdefault("vector_score", None)
            item.setdefault("graph_score", None)
            item.setdefault("rerank_score", item.get("score"))
            item["final_score"] = float(item.get("final_score", item.get("rrf_score", item.get("score", 0.0))) or 0.0)

        meta = {
            "mode": mode,
            "mode_effective": mode_effective,
            "query": query,
            "source_record_count": source_record_count,
            "record_count": record_count,
            "candidate_count": record_count,
            "returned_hit_count": len(returned),
            "bm25_hit_count": len(bm25_hits),
            "dense_hit_count": len(dense_hits),
            "graph_hit_count": len(graph_hits),
            "chunking_enabled": use_chunks,
            "chunk_count": record_count if use_chunks else 0,
            "retrieval_available": bool(records),
            "fallback_used": mode_effective != mode and not (mode == "vector" and mode_effective == "dense"),
            "bm25": bm25_meta,
            "dense": dense_meta,
            "graph": graph_meta,
            "reranker": rerank_meta,
            "loaded_file_count": store_meta.get("loaded_file_count", 0),
            "fallback_json_file_count": store_meta.get("fallback_json_file_count", 0),
            "skipped_files": store_meta.get("skipped_files", []),
            "load_errors": store_meta.get("load_errors", []),
            "failure_reason": _failure_reason(records=records, returned=returned, symbol=symbol, period=period),
        }
        return returned, meta


def _failure_reason(records: list[Any], returned: list[dict[str, Any]], symbol: str | None, period: str | None) -> str:
    if not records:
        if symbol and period:
            return "no_records_for_symbol_period"
        if symbol:
            return "no_records_for_symbol"
        return "no_records"
    if not returned:
        return "no_hits_after_ranking"
    return ""
