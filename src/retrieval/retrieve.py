"""Retrieval service entry points with BM25, vector, hybrid, and reranker paths."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from src.retrieval.bm25_index import BM25Index
from src.retrieval.chroma_index import ChromaIndex
from src.retrieval.chunking import chunk_records
from src.retrieval.evidence_store import EvidenceStore
from src.training.infer_reranker import rerank_hits_with_meta


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

    meta["returned_hit_count"] = len(ranked[:topk])
    meta["failure_reason"] = _failure_reason(records=records, ranked=ranked[:topk], symbol=symbol, period=period)

    if log:
        print(
            f"[retrieval] ranking_mode={ranking_mode} resolved_mode={meta['mode']} "
            f"checkpoint_used={meta['checkpoint_used']} fallback={meta['fallback_used']}"
        )
    return ranked[:topk], meta


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
    index = ChromaIndex()
    index.add_records(records)
    hits = index.search(query=query, topk=topk)
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
        (0.55, bm25_hits, "score"),
        (0.45, vector_hits, "vector_score"),
    ]:
        for rank, item in enumerate(hits, start=1):
            key = str(item.get("sample_id") or item.get("evidence_id") or item.get("source_url") or rank)
            row = merged.setdefault(key, dict(item))
            row["hybrid_score"] = float(row.get("hybrid_score", 0.0)) + (weight / float(rank))
            row["score"] = max(float(row.get("score", 0.0)), float(item.get(score_field, item.get("score", 0.0)) or 0.0))
            if "vector_score" in item:
                row["vector_score"] = float(item.get("vector_score", 0.0) or 0.0)
    output = list(merged.values())
    output.sort(key=lambda item: float(item.get("hybrid_score", 0.0)), reverse=True)
    for item in output:
        item["rerank_score"] = float(item.get("hybrid_score", 0.0))
    return output[:topk]
