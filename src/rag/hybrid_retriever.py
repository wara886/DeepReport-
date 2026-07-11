"""Hybrid RAG retriever composed from BM25, dense, graph, RRF, and reranker."""

from __future__ import annotations

import re
from typing import Any

from src.rag.bm25_retriever import BM25Retriever
from src.rag.dense_retriever import DenseRetriever
from src.rag.graph_retriever import GraphRetriever
from src.rag.reranker_adapter import RerankerAdapter
from src.rag.retrieval_diagnostics import build_retrieval_coverage
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

        fused, section_meta = _apply_section_metadata_boost(query=query, hits=fused)

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
            "vector_hit_count": len(dense_hits),
            "graph_hit_count": len(graph_hits),
            "chunking_enabled": use_chunks,
            "chunk_count": record_count if use_chunks else 0,
            "retrieval_available": bool(records),
            "fallback_used": mode_effective != mode and not (mode == "vector" and mode_effective == "dense"),
            "bm25": bm25_meta,
            "dense": dense_meta,
            "graph": graph_meta,
            "reranker": rerank_meta,
            "section_metadata": section_meta,
            "loaded_file_count": store_meta.get("loaded_file_count", 0),
            "fallback_json_file_count": store_meta.get("fallback_json_file_count", 0),
            "skipped_files": store_meta.get("skipped_files", []),
            "load_errors": store_meta.get("load_errors", []),
            "failure_reason": _failure_reason(records=records, returned=returned, symbol=symbol, period=period),
        }
        _add_component_score_stats(meta, returned)
        meta["coverage"] = build_retrieval_coverage(
            candidates=[record.to_dict() for record in records],
            returned=returned,
            company=symbol,
            mode_effective=mode_effective,
        )
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


SECTION_QUERY_INTENTS: dict[str, dict[str, Any]] = {
    "financial_statements": {
        "terms": [
            "财务报表",
            "利润表",
            "资产负债表",
            "现金流量表",
            "收入",
            "毛利",
            "现金流",
            "revenue",
            "gross profit",
            "cash flow",
            "income statement",
            "balance sheet",
        ],
        "tags": {"收入表现", "利润质量", "现金流", "财务报表"},
    },
    "risk_factors": {
        "terms": ["风险", "风险因素", "风险披露", "监管", "需求波动", "risk", "regulatory", "volatility"],
        "tags": {"风险披露", "需求波动", "监管政策"},
    },
    "business_overview": {
        "terms": ["业务", "主营业务", "产品", "渠道", "收入来源", "business", "segments", "products"],
        "tags": {"业务结构", "主营业务", "收入来源", "产品结构"},
    },
    "management_discussion": {
        "terms": ["管理层讨论", "经营情况", "经营分析", "战略", "management discussion", "md&a"],
        "tags": {"经营分析", "管理层讨论", "战略计划"},
    },
    "ownership_governance": {
        "terms": ["治理", "董事会", "监事会", "高管", "governance", "board"],
        "tags": {"治理结构", "董事会", "内部控制"},
    },
}


def _apply_section_metadata_boost(query: str, hits: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    intents = _detect_section_intents(query)
    if not intents or not hits:
        return hits, {"enabled": bool(hits), "matched_sections": [], "boosted_hit_count": 0}

    boosted_count = 0
    for rank, hit in enumerate(hits):
        base_score = float(hit.get("final_score", hit.get("rrf_score", hit.get("score", 0.0))) or 0.0)
        boost = _section_boost_for_hit(hit, intents)
        if boost > 0:
            boosted_count += 1
            hit["section_boost"] = boost
        hit["final_score"] = base_score + boost
        hit.setdefault("retrieval_rank_before_section_boost", rank + 1)

    ranked = sorted(hits, key=lambda item: float(item.get("final_score", 0.0) or 0.0), reverse=True)
    return ranked, {"enabled": True, "matched_sections": intents, "boosted_hit_count": boosted_count}


def _detect_section_intents(query: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", str(query or "").strip().lower())
    if not normalized:
        return []
    matched: list[str] = []
    for section, config in SECTION_QUERY_INTENTS.items():
        terms = [str(term).lower() for term in config.get("terms", [])]
        if any(term and term in normalized for term in terms):
            matched.append(section)
    return matched


def _section_boost_for_hit(hit: dict[str, Any], intents: list[str]) -> float:
    section_type = str(hit.get("section_type") or "")
    tags = {str(tag) for tag in hit.get("meta_tags", []) if str(tag)}
    boost = 0.0
    for intent in intents:
        if section_type == intent:
            boost += 0.04
        target_tags = SECTION_QUERY_INTENTS.get(intent, {}).get("tags", set())
        if tags.intersection(target_tags):
            boost += 0.02
    return min(boost, 0.08)


def _add_component_score_stats(meta: dict[str, Any], hits: list[dict[str, Any]]) -> None:
    for field in ("bm25_score", "vector_score", "graph_score", "rerank_score", "final_score"):
        scores: list[float] = []
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
