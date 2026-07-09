"""Evidence center query service for the P0 workbench."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session, selectinload

from src.rag.rrf_fusion import reciprocal_rank_fusion
from src.db.models import ClaimEvidence, Company, Document, EvidenceItem, ReportClaim
from src.retrieval.bm25_index import BM25Index, tokenize
from src.retrieval.evidence_store import EvidenceRecord


class EvidenceNotFound(LookupError):
    """Raised when an evidence item does not exist."""


class EvidenceService:
    """List and inspect DB-backed evidence with claim/document joins."""

    def __init__(self, *, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    def list_evidence(
        self,
        *,
        company: str | None = None,
        period: str | None = None,
        source_type: str | None = None,
        trust_level: str | None = None,
        task_id: str | None = None,
        q: str | None = None,
        mode: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit or 50), 200))
        if _is_hybrid_mode(mode) and str(q or "").strip():
            return self.search_evidence(
                query=str(q or ""),
                company=company,
                period=period,
                source_type=source_type,
                trust_level=trust_level,
                task_id=task_id,
                limit=limit,
            )
        with self.session_factory() as session:
            stmt = (
                select(EvidenceItem)
                .options(
                    selectinload(EvidenceItem.company),
                    selectinload(EvidenceItem.document),
                    selectinload(EvidenceItem.claim_links).selectinload(ClaimEvidence.claim),
                )
                .order_by(EvidenceItem.created_at.desc(), EvidenceItem.id.desc())
                .limit(limit)
            )
            stmt = self._apply_filters(
                stmt,
                company=company,
                period=period,
                source_type=source_type,
                trust_level=trust_level,
                task_id=task_id,
                q=q,
            )
            items = [self.serialize_evidence(item, include_content=False) for item in session.scalars(stmt).unique().all()]

        return {"items": items, "total": len(items)}

    def search_evidence(
        self,
        *,
        query: str,
        company: str | None = None,
        period: str | None = None,
        source_type: str | None = None,
        trust_level: str | None = None,
        task_id: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Hybrid DB-backed evidence search for workbench evidence review.

        This is intentionally service-local: it uses persisted evidence rows as
        the source of truth and degrades to keyword/rule ranking when no dense
        vector backend is configured for DB evidence.
        """

        limit = max(1, min(int(limit or 50), 100))
        candidate_limit = max(limit * 8, 200)
        candidate_limit = min(candidate_limit, 1000)
        normalized_query = " ".join(str(query or "").split())
        if not normalized_query:
            return self.list_evidence(
                company=company,
                period=period,
                source_type=source_type,
                trust_level=trust_level,
                task_id=task_id,
                limit=limit,
            )

        with self.session_factory() as session:
            stmt = (
                select(EvidenceItem)
                .options(
                    selectinload(EvidenceItem.company),
                    selectinload(EvidenceItem.document),
                    selectinload(EvidenceItem.claim_links).selectinload(ClaimEvidence.claim),
                )
                .order_by(EvidenceItem.created_at.desc(), EvidenceItem.id.desc())
                .limit(candidate_limit)
            )
            stmt = self._apply_filters(
                stmt,
                company=company,
                period=period,
                source_type=source_type,
                trust_level=trust_level,
                task_id=task_id,
                q=None,
            )
            candidates = list(session.scalars(stmt).unique().all())

        serialized_by_id = {item.evidence_id: self.serialize_evidence(item, include_content=False) for item in candidates}
        records = [_evidence_record_from_item(item) for item in candidates]
        record_ids = {record.evidence_id: record for record in records}

        bm25_hits = _bm25_rank(records=records, query=normalized_query, topk=candidate_limit)
        rule_hits = _rule_rank(
            items=candidates,
            query=normalized_query,
            company=company,
            period=period,
            topk=candidate_limit,
        )
        fused = reciprocal_rank_fusion([bm25_hits, rule_hits], topk=candidate_limit, id_field="evidence_id")
        fused = [_remap_component_names(hit) for hit in fused]
        for hit in fused:
            rule = _hit_by_id(rule_hits, str(hit.get("evidence_id") or ""))
            hit["quality_boost"] = float(rule.get("rule_score", 0.0) if rule else 0.0)
            hit["final_score"] = float(hit.get("rrf_score", 0.0) or 0.0) + (float(hit["quality_boost"]) * 0.01)
        fused.sort(key=lambda item: float(item.get("final_score", 0.0) or 0.0), reverse=True)

        items: list[dict[str, Any]] = []
        for rank, hit in enumerate(fused[:limit], start=1):
            evidence_id = str(hit.get("evidence_id") or "")
            item = dict(serialized_by_id.get(evidence_id) or {})
            if not item:
                continue
            record = record_ids.get(evidence_id)
            rule = _hit_by_id(rule_hits, evidence_id)
            item["search"] = {
                "rank": rank,
                "mode": "hybrid",
                "final_score": round(float(hit.get("final_score", 0.0) or 0.0), 6),
                "bm25_score": _round_optional(hit.get("bm25_score")),
                "rule_score": _round_optional(rule.get("rule_score") if rule else None),
                "source_weight": _round_optional(rule.get("source_weight") if rule else None),
                "company_match": bool(rule.get("company_match")) if rule else False,
                "period_match": bool(rule.get("period_match")) if rule else False,
                "matched_terms": list(rule.get("matched_terms", [])) if rule else _matched_terms(normalized_query, record.searchable_text if record else ""),
                "rank_sources": list(hit.get("rank_sources", [])),
                "reasons": _search_reasons(hit=hit, rule=rule, record=record),
            }
            items.append(item)

        meta = {
            "mode": "hybrid",
            "mode_effective": _mode_effective(bm25_hits=bm25_hits, rule_hits=rule_hits),
            "query": normalized_query,
            "candidate_count": len(candidates),
            "returned_hit_count": len(items),
            "bm25_hit_count": len(bm25_hits),
            "rule_hit_count": len(rule_hits),
            "dense": {
                "available": False,
                "backend": "not_configured",
                "reason": "DB evidence search currently uses keyword and evidence-quality fusion.",
            },
            "fallback_used": True,
            "components": ["关键词召回", "来源可信度/公司/期间匹配"],
            "retrieval_available": bool(candidates),
        }
        meta["coverage"] = _retrieval_coverage(
            candidates=candidates,
            items=items,
            company=company,
            period=period,
            source_type=source_type,
            mode_effective=str(meta["mode_effective"]),
        )
        return {"items": items, "total": len(items), "search_meta": meta}

    def get_evidence(self, evidence_ref: str | int) -> dict[str, Any]:
        with self.session_factory() as session:
            stmt = (
                select(EvidenceItem)
                .options(
                    selectinload(EvidenceItem.company),
                    selectinload(EvidenceItem.document),
                    selectinload(EvidenceItem.claim_links).selectinload(ClaimEvidence.claim),
                )
                .where(_evidence_ref_clause(evidence_ref))
            )
            item = session.scalar(stmt)
            if item is None:
                raise EvidenceNotFound(str(evidence_ref))
            return self.serialize_evidence(item, include_content=True)

    def serialize_evidence(self, item: EvidenceItem, *, include_content: bool) -> dict[str, Any]:
        metadata = item.metadata_json or {}
        claims = [serialize_claim(link.claim) for link in sorted(item.claim_links, key=lambda link: link.claim_id)]
        document = serialize_document(item.document)
        task_ids = sorted({claim["task_id"] for claim in claims if claim.get("task_id")})
        if not task_ids and metadata.get("task_id"):
            task_ids = [str(metadata["task_id"])]
        payload = {
            "id": item.id,
            "evidence_id": item.evidence_id,
            "company_id": item.company_id,
            "company": serialize_company(item),
            "document_id": item.document_id,
            "document": document,
            "chunk_id": item.chunk_id,
            "source_type": item.source_type,
            "trust_level": item.trust_level,
            "title": item.title,
            "snippet": _snippet(item.content),
            "source_url": item.source_url,
            "page_no": item.page_no,
            "metadata": metadata,
            "task_ids": task_ids,
            "claims": claims,
            "claim_count": len(claims),
            "created_at": _dt(item.created_at),
        }
        if include_content:
            payload["content"] = item.content
        return payload

    def _apply_filters(
        self,
        stmt: Select[tuple[EvidenceItem]],
        *,
        company: str | None,
        period: str | None,
        source_type: str | None,
        trust_level: str | None,
        task_id: str | None,
        q: str | None,
    ) -> Select[tuple[EvidenceItem]]:
        if source_type:
            stmt = stmt.where(EvidenceItem.source_type == source_type)
        if trust_level:
            stmt = stmt.where(EvidenceItem.trust_level == trust_level)
        if company:
            normalized = f"%{company.strip()}%"
            stmt = stmt.where(
                EvidenceItem.company.has(
                    or_(
                        Company.name.ilike(normalized),
                        Company.symbol.ilike(normalized),
                    )
                )
            )
        if period:
            normalized_period = period.strip()
            stmt = stmt.where(
                or_(
                    EvidenceItem.document.has(Document.report_period == normalized_period),
                    EvidenceItem.metadata_json["period"].as_string() == normalized_period,
                )
            )
        if task_id:
            normalized_task_id = task_id.strip()
            stmt = stmt.where(
                or_(
                    EvidenceItem.claim_links.any(
                        ClaimEvidence.claim.has(ReportClaim.task_id == normalized_task_id)
                    ),
                    EvidenceItem.metadata_json["task_id"].as_string() == normalized_task_id,
                    EvidenceItem.document.has(Document.batch_id == normalized_task_id),
                )
            )
        if q:
            needle = f"%{q.strip()}%"
            stmt = stmt.where(
                or_(
                    EvidenceItem.evidence_id.ilike(needle),
                    EvidenceItem.title.ilike(needle),
                    EvidenceItem.content.ilike(needle),
                    EvidenceItem.source_url.ilike(needle),
                )
            )
        return stmt


def serialize_company(item: EvidenceItem) -> dict[str, Any] | None:
    if item.company is None:
        return None
    return {
        "id": item.company.id,
        "name": item.company.name,
        "symbol": item.company.symbol,
        "market": item.company.market,
        "industry": item.company.industry,
    }


def serialize_document(document: Document | None) -> dict[str, Any] | None:
    if document is None:
        return None
    return {
        "id": document.id,
        "company_id": document.company_id,
        "datasource_id": document.datasource_id,
        "batch_id": document.batch_id,
        "title": document.title,
        "doc_type": document.doc_type,
        "report_period": document.report_period,
        "source_url": document.source_url,
        "file_path": document.file_path,
        "parse_status": document.parse_status,
        "created_at": _dt(document.created_at),
    }


def serialize_claim(claim: ReportClaim) -> dict[str, Any]:
    return {
        "id": claim.id,
        "task_id": claim.task_id,
        "section_name": claim.section_name,
        "claim_text": claim.claim_text,
        "claim_type": claim.claim_type,
        "is_critical": claim.is_critical,
        "critical_claim_type": claim.critical_claim_type,
        "verification_status": claim.verification_status,
        "numeric_check_status": claim.numeric_check_status,
        "citation_check_status": claim.citation_check_status,
        "confidence": claim.confidence,
        "review_status": claim.review_status,
        "metadata": claim.metadata_json or {},
    }


def _evidence_ref_clause(evidence_ref: str | int) -> Any:
    text = str(evidence_ref).strip()
    if text.isdigit():
        return or_(EvidenceItem.id == int(text), EvidenceItem.evidence_id == text)
    return EvidenceItem.evidence_id == text


def _snippet(content: str | None, *, limit: int = 220) -> str:
    text = " ".join(str(content or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _is_hybrid_mode(mode: str | None) -> bool:
    return str(mode or "").strip().lower() in {"hybrid", "smart", "hybrid_rag"}


def _evidence_record_from_item(item: EvidenceItem) -> EvidenceRecord:
    metadata = item.metadata_json or {}
    document = item.document
    company = item.company
    symbol = str(
        (company.symbol if company else "")
        or metadata.get("symbol")
        or metadata.get("company_symbol")
        or ""
    )
    period = str(
        (document.report_period if document else "")
        or metadata.get("period")
        or metadata.get("report_period")
        or ""
    )
    return EvidenceRecord.from_dict(
        {
            "sample_id": item.evidence_id,
            "evidence_id": item.evidence_id,
            "source_type": item.source_type or "",
            "symbol": symbol,
            "period": period,
            "title": item.title or "",
            "content": item.content or "",
            "source_url": item.source_url or (document.source_url if document else "") or "",
            "trust_level": item.trust_level or "",
            "publish_time": str(metadata.get("publish_time") or metadata.get("source_timestamp") or ""),
        }
    )


def _bm25_rank(*, records: list[EvidenceRecord], query: str, topk: int) -> list[dict[str, Any]]:
    hits = []
    for hit in BM25Index(records).search(query=query, topk=topk):
        row = hit.record.to_dict()
        row["score"] = float(hit.score)
        row["bm25_score"] = float(hit.score)
        hits.append(row)
    return hits


def _rule_rank(
    *,
    items: list[EvidenceItem],
    query: str,
    company: str | None,
    period: str | None,
    topk: int,
) -> list[dict[str, Any]]:
    rows = []
    for item in items:
        record = _evidence_record_from_item(item)
        matched = _matched_terms(query, record.searchable_text)
        company_match = _company_matches(item, company) or _query_mentions_company(query, item)
        period_match = _period_matches(item, period) or _query_mentions_period(query, record.period)
        source_weight = _source_weight(item)
        if not matched and not company_match and not period_match:
            continue
        overlap_score = min(len(matched) / max(len(set(tokenize(query))), 1), 1.0)
        rule_score = (
            source_weight * 0.42
            + (1.0 if company_match else 0.0) * 0.22
            + (1.0 if period_match else 0.0) * 0.18
            + overlap_score * 0.18
        )
        row = record.to_dict()
        row.update(
            {
                "score": float(rule_score),
                "rule_score": float(rule_score),
                "source_weight": float(source_weight),
                "company_match": bool(company_match),
                "period_match": bool(period_match),
                "matched_terms": matched,
            }
        )
        rows.append(row)
    rows.sort(key=lambda item: float(item.get("rule_score", 0.0) or 0.0), reverse=True)
    return rows[:topk]


def _source_weight(item: EvidenceItem) -> float:
    source = str(item.source_type or "").lower()
    trust = str(item.trust_level or "").lower()
    if trust == "official" or source in {
        "sec_edgar",
        "sec_filing",
        "cninfo",
        "cninfo_announcement",
        "cninfo_announcements",
        "hkex",
        "hkex_announcement",
        "hkex_announcements",
        "hkex_annual_report",
    }:
        return 1.0
    if trust == "primary" or source in {"financials", "filing", "filings", "local_pdf"}:
        return 0.78
    if trust == "secondary" or source in {"news", "web_search", "serper", "tavily"}:
        return 0.38
    return 0.52


def _company_matches(item: EvidenceItem, company: str | None) -> bool:
    needle = _norm(company)
    if not needle:
        return False
    company_obj = item.company
    values = [
        company_obj.name if company_obj else "",
        company_obj.symbol if company_obj else "",
        *((company_obj.aliases or []) if company_obj else []),
        str((item.metadata_json or {}).get("symbol") or ""),
        str((item.metadata_json or {}).get("company_name") or ""),
    ]
    return any(needle in _norm(value) or _norm(value) in needle for value in values if value)


def _query_mentions_company(query: str, item: EvidenceItem) -> bool:
    company_obj = item.company
    if company_obj is None:
        return False
    query_norm = _norm(query)
    values = [company_obj.symbol or "", company_obj.name or "", *(company_obj.aliases or [])]
    return any(_norm(value) and _norm(value) in query_norm for value in values)


def _period_matches(item: EvidenceItem, period: str | None) -> bool:
    expected = _norm(period)
    if not expected:
        return False
    item_period = _norm(_evidence_record_from_item(item).period)
    return bool(item_period and item_period == expected)


def _query_mentions_period(query: str, item_period: str | None) -> bool:
    period_norm = _norm(item_period)
    return bool(period_norm and period_norm in _norm(query))


def _matched_terms(query: str, text: str) -> list[str]:
    query_terms = list(dict.fromkeys(tokenize(query)))
    text_terms = set(tokenize(text))
    return [term for term in query_terms if term in text_terms][:6]


def _hit_by_id(hits: list[dict[str, Any]], evidence_id: str) -> dict[str, Any]:
    for hit in hits:
        if str(hit.get("evidence_id") or "") == evidence_id:
            return hit
    return {}


def _remap_component_names(hit: dict[str, Any]) -> dict[str, Any]:
    name_map = {"bm25": "keyword", "dense": "evidence_quality"}
    output = dict(hit)
    output["rank_sources"] = [name_map.get(str(name), str(name)) for name in output.get("rank_sources", [])]
    component_ranks = output.get("component_ranks", {})
    if isinstance(component_ranks, dict):
        output["component_ranks"] = {name_map.get(str(key), str(key)): value for key, value in component_ranks.items()}
    return output


def _search_reasons(
    *,
    hit: dict[str, Any],
    rule: dict[str, Any],
    record: EvidenceRecord | None,
) -> list[str]:
    reasons: list[str] = []
    rank_sources = set(str(source) for source in hit.get("rank_sources", []))
    if len(rank_sources) >= 2:
        reasons.append("关键词与证据质量排序同时命中")
    elif "keyword" in rank_sources:
        reasons.append("关键词召回命中")
    if float(rule.get("source_weight", 0.0) or 0.0) >= 0.95:
        reasons.append("官方披露来源优先")
    elif float(rule.get("source_weight", 0.0) or 0.0) >= 0.75:
        reasons.append("一手资料来源")
    if rule.get("company_match"):
        reasons.append("公司匹配")
    if rule.get("period_match"):
        reasons.append("期间匹配")
    matched_terms = list(rule.get("matched_terms", [])) if rule else []
    if matched_terms:
        reasons.append("命中词：" + "、".join(matched_terms[:4]))
    if not reasons and record is not None:
        reasons.append("按证据相关度排序")
    return reasons[:5]


def _mode_effective(*, bm25_hits: list[dict[str, Any]], rule_hits: list[dict[str, Any]]) -> str:
    if bm25_hits and rule_hits:
        return "keyword_quality_fusion"
    if bm25_hits:
        return "keyword_only"
    if rule_hits:
        return "quality_rule_only"
    return "no_hits"


def _retrieval_coverage(
    *,
    candidates: list[EvidenceItem],
    items: list[dict[str, Any]],
    company: str | None,
    period: str | None,
    source_type: str | None,
    mode_effective: str,
) -> dict[str, Any]:
    returned_sources = sorted({str(item.get("source_type") or "") for item in items if item.get("source_type")})
    candidate_sources = sorted({str(item.source_type or "") for item in candidates if item.source_type})
    required_sources = _required_sources_for_query(company=company, source_type=source_type)
    missing_sources = [source for source in required_sources if source not in returned_sources]
    gaps: list[dict[str, Any]] = []
    if not candidates:
        gaps.append(
            {
                "type": "no_candidates",
                "label": "没有候选证据",
                "description": "当前筛选条件下没有可检索证据，请先补充采集或手动导入资料。",
                "next_view": "ingestion",
            }
        )
    elif not items:
        gaps.append(
            {
                "type": "no_hits",
                "label": "没有命中证据",
                "description": "已有候选证据，但查询词、公司或期间没有形成有效命中。",
                "next_view": "evidence",
            }
        )
    if missing_sources:
        gaps.append(
            {
                "type": "source_gap",
                "label": "来源覆盖不足",
                "description": "当前结果缺少：" + "、".join(missing_sources),
                "sources": missing_sources,
                "next_view": "datasources",
            }
        )
    if mode_effective in {"keyword_only", "quality_rule_only"}:
        gaps.append(
            {
                "type": "fusion_degraded",
                "label": "融合信号不足",
                "description": "当前检索只命中了单一路径，建议补充更多证据或更具体的查询词。",
                "next_view": "manual",
            }
        )
    if mode_effective == "no_hits":
        gaps.append(
            {
                "type": "retrieval_failed",
                "label": "检索未命中",
                "description": "没有可用于支持研报主张的召回结果，正式研报不应引用该查询结果。",
                "next_view": "ingestion",
            }
        )
    return {
        "candidate_count": len(candidates),
        "returned_count": len(items),
        "candidate_sources": candidate_sources,
        "returned_sources": returned_sources,
        "required_sources": required_sources,
        "missing_sources": missing_sources,
        "evidence_ready": bool(items),
        "quality_ready": bool(items) and not missing_sources,
        "gaps": gaps,
        "summary": _coverage_summary(
            candidate_count=len(candidates),
            returned_count=len(items),
            missing_sources=missing_sources,
            mode_effective=mode_effective,
        ),
    }


def _required_sources_for_query(*, company: str | None, source_type: str | None) -> list[str]:
    if source_type:
        return [source_type]
    normalized = _norm(company)
    if not normalized:
        return []
    if any(token in normalized for token in ["nvda", "nvidia", "aapl", "apple", "msft", "tesla", "tsla", "baba"]):
        return ["sec_edgar"]
    if any(token in normalized for token in ["0700", "tencent", "9988"]):
        return ["hkex"]
    if any(token in normalized for token in ["600", "300", "002", "贵州", "宁德", "比亚迪"]):
        return ["cninfo"]
    return []


def _coverage_summary(*, candidate_count: int, returned_count: int, missing_sources: list[str], mode_effective: str) -> str:
    if returned_count <= 0:
        return "未召回可用证据，需要补充来源或调整查询。"
    if missing_sources:
        return "已召回证据，但来源覆盖仍需补齐。"
    if mode_effective in {"keyword_quality_fusion"}:
        return "关键词和证据质量信号同时命中，可进入证据复核。"
    if candidate_count > returned_count:
        return "已从候选证据中筛出相关结果，建议继续核对原文。"
    return "已召回可复核证据。"


def _round_optional(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None


def _norm(value: Any) -> str:
    return "".join(str(value or "").lower().split())
