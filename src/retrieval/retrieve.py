"""Retrieval service entry points with BM25, vector, hybrid, and reranker paths."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from src.retrieval.bm25_index import BM25Index
from src.retrieval.chroma_index import ChromaIndex
from src.retrieval.chunking import chunk_records
from src.retrieval.evidence_store import EvidenceStore
from src.training.infer_reranker import rerank_hits_with_meta
from src.utils.logging import get_task_logger, log_vector_search

logger = get_task_logger(__name__, task_id="-")


def retrieve_evidence(
    query: str,
    topk: int = 5,
    symbol: Optional[str] = None,
    period: Optional[str] = None,
    curated_dir: str = "data/curated",
    use_chunks: bool = False,
) -> List[Dict[str, object]]:
    store = EvidenceStore.from_curated_parquet(curated_dir=curated_dir)
    records = store.filter(symbol=symbol, period=period)
    if use_chunks:
        records = chunk_records(records)
    index = BM25Index(records)
    hits = index.search(query=query, topk=topk)

    output: List[Dict[str, object]] = []
    for hit in hits:
        item = hit.record.to_dict()
        item["bm25_score"] = float(hit.score)
        item["score"] = float(hit.score)
        output.append(item)
    return output


def retrieve_evidence_with_mode(
    query: str,
    topk: int = 5,
    symbol: Optional[str] = None,
    period: Optional[str] = None,
    curated_dir: str = "data/curated",
    ranking_mode: str = "bm25",
    reranker_checkpoint_path: str = "data/outputs/checkpoints/reranker_checkpoint.json",
    use_chunks: bool = False,
    log: bool = True,
) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    store = EvidenceStore.from_curated_parquet(curated_dir=curated_dir)
    store_meta = dict(getattr(store, "load_meta", {}) or {})
    records = store.filter(symbol=symbol, period=period)
    source_record_count = len(records)
    if use_chunks:
        records = chunk_records(records)
    bm25_hits = _bm25_hits(records=records, query=query, topk=topk)

    mode = ranking_mode.strip().lower()
    vector_hits: List[Dict[str, object]] = []
    if mode in {"vector", "hybrid", "hybrid_rerank"}:
        vector_hits, vector_meta = _vector_hits(records=records, query=query, topk=topk)
    else:
        vector_meta = {"backend": "disabled"}

    if mode == "vector":
        ranked = [dict(item, rerank_score=float(item.get("vector_score", item.get("score", 0.0)) or 0.0)) for item in vector_hits]
        meta = {
            "mode": "vector",
            "checkpoint_path": reranker_checkpoint_path,
            "checkpoint_used": False,
            "fallback_used": False,
            "query": query,
            "source_record_count": source_record_count,
            "record_count": len(records),
            "bm25_hit_count": len(bm25_hits),
            "vector_hit_count": len(vector_hits),
            "chunking_enabled": use_chunks,
            "chunk_count": len(records) if use_chunks else 0,
            "vector_backend": vector_meta.get("backend", "memory"),
        }
    elif mode == "hybrid":
        ranked = _hybrid_rank(bm25_hits=bm25_hits, vector_hits=vector_hits, topk=topk)
        meta = {
            "mode": "hybrid",
            "checkpoint_path": reranker_checkpoint_path,
            "checkpoint_used": False,
            "fallback_used": False,
            "query": query,
            "source_record_count": source_record_count,
            "record_count": len(records),
            "bm25_hit_count": len(bm25_hits),
            "vector_hit_count": len(vector_hits),
            "chunking_enabled": use_chunks,
            "chunk_count": len(records) if use_chunks else 0,
            "vector_backend": vector_meta.get("backend", "memory"),
        }
    elif mode in {"reranker", "hybrid_rerank"}:
        seed_hits = _hybrid_rank(bm25_hits=bm25_hits, vector_hits=vector_hits, topk=max(topk * 2, topk)) if mode == "hybrid_rerank" else bm25_hits
        ranked, meta = rerank_hits_with_meta(hits=seed_hits, query=query, checkpoint_path=reranker_checkpoint_path)
        if mode == "hybrid_rerank":
            meta["mode"] = "hybrid_rerank"
            meta["vector_backend"] = vector_meta.get("backend", "memory")
            meta["vector_hit_count"] = len(vector_hits)
        meta["query"] = query
        meta["source_record_count"] = source_record_count
        meta["record_count"] = len(records)
        meta["bm25_hit_count"] = len(bm25_hits)
        meta["chunking_enabled"] = use_chunks
        meta["chunk_count"] = len(records) if use_chunks else 0
    else:
        ranked = [dict(item, rerank_score=float(item.get("score", 0.0))) for item in bm25_hits]
        meta = {
            "mode": "bm25",
            "checkpoint_path": reranker_checkpoint_path,
            "checkpoint_used": False,
            "fallback_used": False,
            "query": query,
            "source_record_count": source_record_count,
            "record_count": len(records),
            "bm25_hit_count": len(bm25_hits),
            "vector_hit_count": 0,
            "chunking_enabled": use_chunks,
            "chunk_count": len(records) if use_chunks else 0,
        }

    returned_hits = ranked[:topk]
    for item in returned_hits:
        item.setdefault("bm25_score", None)
        item.setdefault("vector_score", None)
        item.setdefault("rerank_score", item.get("score"))
        item["final_score"] = float(
            item.get("rerank_score", item.get("vector_score", item.get("bm25_score", item.get("score", 0.0)))) or 0.0
        )
    meta["returned_hit_count"] = len(returned_hits)
    meta["candidate_count"] = len(records)
    meta["reranked_count"] = len(ranked)
    meta["retrieval_available"] = bool(records)
    if not records:
        meta["fallback_reason"] = "no_curated_records_loaded"
        if store_meta.get("load_errors"):
            meta["fallback_reason"] = "curated_load_failed"
        if meta.get("mode") in {"vector", "hybrid", "hybrid_rerank"}:
            meta["mode_effective"] = "unavailable"
    _add_score_stats(meta, returned_hits)
    _add_component_score_stats(meta, returned_hits)
    meta["failure_reason"] = _failure_reason(records=records, ranked=returned_hits, symbol=symbol, period=period)
    meta["loaded_file_count"] = store_meta.get("loaded_file_count", 0)
    meta["fallback_json_file_count"] = store_meta.get("fallback_json_file_count", 0)
    meta["skipped_files"] = store_meta.get("skipped_files", [])
    meta["load_errors"] = store_meta.get("load_errors", [])

    if log:
        logger.info(
            "retrieval | mode=%s | query=\"%s\" | hits=%d | bm25=%d | vector=%d | rerank=%s",
            meta["mode"], query[:80], len(ranked[:topk]),
            meta.get("bm25_hit_count", 0), meta.get("vector_hit_count", 0),
            meta.get("checkpoint_used", False),
        )
    # 记录 top-3 相似度分数，方便调试召回质量
    top_scores = [float(h.get("final_score", 0.0) or 0.0) for h in returned_hits[:3]]
    if top_scores:
        log_vector_search(
            logger, query, topk, len(ranked[:topk]), top_scores,
            mode=meta["mode"], symbol=symbol or "", period=period or "",
        )
    return returned_hits, meta


def _add_score_stats(meta: Dict[str, object], hits: List[Dict[str, object]]) -> None:
    scores = []
    for hit in hits:
        value = hit.get("rerank_score", hit.get("vector_score", hit.get("score")))
        try:
            scores.append(float(value))
        except (TypeError, ValueError):
            continue
    if not scores:
        meta["score_min"] = None
        meta["score_max"] = None
        meta["score_mean"] = None
        return
    meta["score_min"] = min(scores)
    meta["score_max"] = max(scores)
    meta["score_mean"] = sum(scores) / len(scores)


def _add_component_score_stats(meta: Dict[str, object], hits: List[Dict[str, object]]) -> None:
    for field in ("bm25_score", "vector_score", "rerank_score", "final_score"):
        scores = []
        for hit in hits:
            value = hit.get(field)
            if value is None:
                continue
            try:
                scores.append(float(value))
            except (TypeError, ValueError):
                continue
        prefix = field.removesuffix("_score")
        meta[f"{prefix}_score_min"] = min(scores) if scores else None
        meta[f"{prefix}_score_max"] = max(scores) if scores else None
        meta[f"{prefix}_score_mean"] = (sum(scores) / len(scores)) if scores else None


def _failure_reason(
    records: List[object],
    ranked: List[Dict[str, object]],
    symbol: Optional[str],
    period: Optional[str],
) -> str:
    if not records:
        if symbol and period:
            return "no_records_for_symbol_period"
        if symbol:
            return "no_records_for_symbol"
        return "no_records"
    if not ranked:
        return "no_hits_after_ranking"
    return ""


def _bm25_hits(records: List[object], query: str, topk: int) -> List[Dict[str, object]]:
    index = BM25Index(records)
    hits = index.search(query=query, topk=topk)
    output: List[Dict[str, object]] = []
    for hit in hits:
        item = hit.record.to_dict()
        item["score"] = float(hit.score)
        output.append(item)
    return output


def _vector_hits(records: List[object], query: str, topk: int) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    try:
        index = ChromaIndex()
        index.add_records(records)
        hits = index.search(query=query, topk=topk)
    except Exception as exc:
        logger.warning("Chroma vector search failed, falling back to BM25-only: %s", exc)
        return [], {"backend": "disabled", "error": str(exc)}
    output = []
    for item in hits:
        row = dict(item)
        row["score"] = float(row.get("vector_score", 0.0))
        output.append(row)
    return output, {"backend": index.backend}


def _hybrid_rank(
    bm25_hits: List[Dict[str, object]],
    vector_hits: List[Dict[str, object]],
    topk: int,
) -> List[Dict[str, object]]:
    merged: Dict[str, Dict[str, object]] = {}
    for weight, hits, score_field in [
        (0.55, bm25_hits, "bm25_score"),
        (0.45, vector_hits, "vector_score"),
    ]:
        for rank, item in enumerate(hits, start=1):
            key = str(item.get("sample_id") or item.get("evidence_id") or item.get("source_url") or rank)
            row = merged.setdefault(key, dict(item))
            row["hybrid_score"] = float(row.get("hybrid_score", 0.0)) + (weight / float(rank))
            row["score"] = max(float(row.get("score", 0.0)), float(item.get(score_field, item.get("score", 0.0)) or 0.0))
            if "bm25_score" in item:
                row["bm25_score"] = float(item.get("bm25_score", 0.0) or 0.0)
            if "vector_score" in item:
                row["vector_score"] = float(item.get("vector_score", 0.0) or 0.0)
    output = list(merged.values())
    output.sort(key=lambda item: float(item.get("hybrid_score", 0.0)), reverse=True)
    for item in output:
        item["rerank_score"] = float(item.get("hybrid_score", 0.0))
        item["final_score"] = float(item["rerank_score"])
    return output[:topk]
