"""Retrieval service entry points with optional reranker path."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from src.retrieval.bm25_index import BM25Index
from src.retrieval.evidence_store import EvidenceStore
from src.training.infer_reranker import rerank_hits_with_meta


def retrieve_evidence(
    query: str,
    topk: int = 5,
    symbol: Optional[str] = None,
    period: Optional[str] = None,
    curated_dir: str = "data/curated",
) -> List[Dict[str, object]]:
    store = EvidenceStore.from_curated_parquet(curated_dir=curated_dir)
    records = store.filter(symbol=symbol, period=period)
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
    log: bool = True,
) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    hits = retrieve_evidence(
        query=query,
        topk=topk,
        symbol=symbol,
        period=period,
        curated_dir=curated_dir,
    )

    mode = ranking_mode.strip().lower()
    if mode == "reranker":
        ranked, meta = rerank_hits_with_meta(hits=hits, checkpoint_path=reranker_checkpoint_path)
    else:
        ranked = [dict(item, rerank_score=float(item.get("score", 0.0))) for item in hits]
        meta = {
            "mode": "bm25",
            "checkpoint_path": reranker_checkpoint_path,
            "checkpoint_used": False,
            "fallback_used": False,
        }

    if log:
        print(
            f"[retrieval] ranking_mode={ranking_mode} resolved_mode={meta['mode']} "
            f"checkpoint_used={meta['checkpoint_used']} fallback={meta['fallback_used']}"
        )
    return ranked, meta
