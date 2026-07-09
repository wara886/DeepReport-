"""Task-level analysis package for the workbench detail view."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
import json
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from src.db.models import (
    ClaimEvidence,
    Company,
    Entity,
    EntityRelation,
    EvidenceItem,
    FinancialFact,
    InvestmentSignal,
    ReportClaim,
    ReportTask,
)
from src.rag.retrieval_diagnostics import build_retrieval_coverage
from src.services.claim_review_service import ClaimReviewService
from src.services.financial_fact_service import FinancialFactService
from src.services.investment_signal_service import InvestmentSignalService
from src.services.report_task_service import ReportTaskNotFound, ReportTaskService


class TaskAnalysisService:
    """Build a product-facing analysis package around one report task.

    The package is read-only and intentionally uses existing P0/P2.3 tables:
    report tasks, evidence, facts, investment signals, claims, and quality
    diagnostics. It does not introduce a new graph backend.
    """

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        report_task_service: ReportTaskService,
    ) -> None:
        self.session_factory = session_factory
        self.report_task_service = report_task_service
        self.claim_service = ClaimReviewService(session_factory=session_factory)
        self.fact_service = FinancialFactService(session_factory=session_factory)
        self.signal_service = InvestmentSignalService(session_factory=session_factory)

    def get_analysis_package(self, task_id: str) -> dict[str, Any]:
        task_payload = self.report_task_service.get_task(task_id)
        with self.session_factory() as session:
            task = _get_task(session, task_id)
            symbol = str(task.symbol or "").strip().upper()
            period = str(task.period or "").strip().upper()
            company_id = task.company_id
            company_name = str((task.metadata_json or {}).get("company_name") or symbol)

            claims = _claims_for_task(session, task_id)
            evidence_candidates = _evidence_candidates_for_task(session, task_id=task_id, symbol=symbol, company_id=company_id)
            evidence_items = _filter_evidence_by_period(evidence_candidates, period=period)
            entity_memory = _build_entity_memory(session, task_id=task_id, evidence_items=evidence_items)
            facts = _facts_for_task(session, symbol=symbol, company_id=company_id, period=period)
            signals = _signals_for_task(session, task_id=task_id, symbol=symbol, company_id=company_id, period=period)

        evidence_payloads = [_serialize_evidence(item) for item in evidence_items[:40]]
        candidate_payloads = [_serialize_evidence(item) for item in evidence_candidates[:80]]
        fact_payloads = [self.fact_service.serialize_fact(item) for item in facts[:40]]
        signal_payloads = [self.signal_service.serialize_signal(item) for item in signals[:30]]
        claim_payloads = [self.claim_service.serialize_claim(item, include_evidence=True) for item in claims[:50]]

        stats = _build_stats(
            evidence=evidence_payloads,
            facts=fact_payloads,
            signals=signal_payloads,
            claims=claim_payloads,
        )
        signal_summary = _build_signal_summary(signal_payloads)
        citation_artifacts = _load_citation_artifacts(task_payload)
        citation_usage = _build_citation_usage(
            claims=claim_payloads,
            citations=citation_artifacts["citations"],
            report_text=citation_artifacts["report_text"],
        )
        retrieval_coverage = build_retrieval_coverage(
            candidates=candidate_payloads,
            returned=evidence_payloads,
            company=symbol,
            mode_effective=_retrieval_mode(candidate_payloads=candidate_payloads, evidence_payloads=evidence_payloads),
        )
        retrieval_diagnostics = _build_retrieval_diagnostics(
            task_payload=task_payload,
            company_name=company_name,
            symbol=symbol,
            period=period,
            candidate_payloads=candidate_payloads,
            evidence_payloads=evidence_payloads,
            retrieval_coverage=retrieval_coverage,
        )
        quality_proof = _build_quality_proof(
            task_payload=task_payload,
            stats=stats,
            claims=claim_payloads,
            citation_usage=citation_usage,
            retrieval_coverage=retrieval_coverage,
        )
        argument_chain = _build_argument_chain(
            company_name=company_name,
            symbol=symbol,
            period=period,
            facts=fact_payloads,
            signals=signal_payloads,
            claims=claim_payloads,
            evidence=evidence_payloads,
        )
        risk_chain = _build_risk_chain(
            company_name=company_name,
            symbol=symbol,
            period=period,
            signals=signal_payloads,
            claims=claim_payloads,
            evidence=evidence_payloads,
        )
        narrative = _build_narrative(task_payload=task_payload, stats=stats, entity_memory=entity_memory)
        recommended_actions = _recommended_actions(
            task_payload=task_payload,
            stats=stats,
            entity_memory=entity_memory,
            quality_proof=quality_proof,
            retrieval_coverage=retrieval_coverage,
            argument_chain=argument_chain,
            risk_chain=risk_chain,
        )

        return {
            "task": task_payload,
            "scope": {
                "company_name": company_name,
                "symbol": symbol,
                "period": period,
                "report_type": task_payload.get("report_type"),
            },
            "stats": stats,
            "retrieval_coverage": retrieval_coverage,
            "retrieval_diagnostics": retrieval_diagnostics,
            "citation_usage": citation_usage,
            "entity_memory": entity_memory,
            "signal_summary": signal_summary,
            "narrative": narrative,
            "quality_proof": quality_proof,
            "argument_chain": argument_chain,
            "risk_chain": risk_chain,
            "recommended_actions": recommended_actions,
            "evidence": evidence_payloads,
            "financial_facts": fact_payloads,
            "investment_signals": signal_payloads,
            "claims": claim_payloads,
        }


def _get_task(session: Session, task_id: str) -> ReportTask:
    task = session.scalar(select(ReportTask).where(ReportTask.task_id == task_id))
    if task is None:
        raise ReportTaskNotFound(task_id)
    return task


def _claims_for_task(session: Session, task_id: str) -> list[ReportClaim]:
    return list(
        session.scalars(
            select(ReportClaim)
            .where(ReportClaim.task_id == task_id)
            .options(selectinload(ReportClaim.evidence_links).selectinload(ClaimEvidence.evidence_item))
            .order_by(ReportClaim.id.desc())
        )
        .unique()
        .all()
    )


def _evidence_candidates_for_task(
    session: Session,
    *,
    task_id: str,
    symbol: str,
    company_id: int | None,
) -> list[EvidenceItem]:
    clauses: list[Any] = [
        EvidenceItem.claim_links.any(ClaimEvidence.claim.has(ReportClaim.task_id == task_id)),
        EvidenceItem.metadata_json["task_id"].as_string() == task_id,
    ]
    if company_id:
        clauses.append(EvidenceItem.company_id == company_id)
    if symbol:
        clauses.append(EvidenceItem.company.has(Company.symbol == symbol))
    stmt = (
        select(EvidenceItem)
        .options(
            selectinload(EvidenceItem.company),
            selectinload(EvidenceItem.document),
            selectinload(EvidenceItem.claim_links).selectinload(ClaimEvidence.claim),
        )
        .where(or_(*clauses))
        .order_by(EvidenceItem.created_at.desc(), EvidenceItem.id.desc())
        .limit(200)
    )
    return list(session.scalars(stmt).unique().all())


def _filter_evidence_by_period(items: list[EvidenceItem], *, period: str) -> list[EvidenceItem]:
    if not period:
        return items
    scoped: list[EvidenceItem] = []
    for item in items:
        metadata = item.metadata_json or {}
        doc_period = item.document.report_period if item.document else None
        if not doc_period and metadata.get("period"):
            doc_period = str(metadata.get("period"))
        if not doc_period or str(doc_period).upper() == period:
            scoped.append(item)
    return scoped


def _facts_for_task(session: Session, *, symbol: str, company_id: int | None, period: str) -> list[FinancialFact]:
    stmt = (
        select(FinancialFact)
        .options(selectinload(FinancialFact.company), selectinload(FinancialFact.evidence_item))
        .order_by(FinancialFact.created_at.desc(), FinancialFact.id.desc())
        .limit(200)
    )
    filters: list[Any] = []
    if company_id:
        filters.append(FinancialFact.company_id == company_id)
    if symbol:
        filters.append(FinancialFact.company.has(Company.symbol == symbol))
    if filters:
        stmt = stmt.where(or_(*filters))
    if period:
        stmt = stmt.where(FinancialFact.period == period)
    return list(session.scalars(stmt).unique().all())


def _signals_for_task(
    session: Session,
    *,
    task_id: str,
    symbol: str,
    company_id: int | None,
    period: str,
) -> list[InvestmentSignal]:
    stmt = (
        select(InvestmentSignal)
        .options(
            selectinload(InvestmentSignal.company),
            selectinload(InvestmentSignal.evidence_item),
            selectinload(InvestmentSignal.source_fact).selectinload(FinancialFact.evidence_item),
            selectinload(InvestmentSignal.task),
        )
        .order_by(InvestmentSignal.updated_at.desc(), InvestmentSignal.id.desc())
        .limit(120)
    )
    filters: list[Any] = [InvestmentSignal.task_id == task_id]
    if company_id:
        filters.append(InvestmentSignal.company_id == company_id)
    if symbol:
        filters.append(InvestmentSignal.company.has(Company.symbol == symbol))
    stmt = stmt.where(or_(*filters))
    if period:
        stmt = stmt.where(or_(InvestmentSignal.period == period, InvestmentSignal.period.is_(None)))
    return list(session.scalars(stmt).unique().all())


def _serialize_evidence(item: EvidenceItem) -> dict[str, Any]:
    claims = [link.claim for link in item.claim_links]
    metadata = item.metadata_json or {}
    return {
        "id": item.id,
        "evidence_id": item.evidence_id,
        "company_id": item.company_id,
        "company": {
            "id": item.company.id,
            "name": item.company.name,
            "symbol": item.company.symbol,
            "market": item.company.market,
        }
        if item.company
        else None,
        "document_id": item.document_id,
        "document": {
            "id": item.document.id,
            "title": item.document.title,
            "doc_type": item.document.doc_type,
            "report_period": item.document.report_period,
            "source_url": item.document.source_url,
        }
        if item.document
        else None,
        "source_type": item.source_type,
        "trust_level": item.trust_level,
        "title": item.title,
        "snippet": _snippet(item.content),
        "source_url": item.source_url,
        "page_no": item.page_no,
        "metadata": metadata,
        "claim_count": len(claims),
        "claim_ids": [claim.id for claim in claims],
    }


def _build_entity_memory(session: Session, *, task_id: str, evidence_items: list[EvidenceItem]) -> dict[str, Any]:
    evidence_ids = [item.id for item in evidence_items]
    if not evidence_ids:
        return {
            "task_id": task_id,
            "ready": False,
            "source_evidence_count": 0,
            "entity_count": 0,
            "relation_count": 0,
            "type_distribution": [],
            "relation_distribution": [],
            "sample_entities": [],
            "sample_relations": [],
            "summary": "当前任务还没有可沉淀的证据，先补充或导入任务资料。",
            "recommended_actions": [{"label": "补充证据", "view": "evidence", "reason": "结构化记忆需要先有任务证据池。"}],
        }

    entities = list(
        session.scalars(
            select(Entity)
            .where(Entity.source_evidence_item_id.in_(evidence_ids))
            .options(selectinload(Entity.source_evidence_item))
            .order_by(Entity.updated_at.desc(), Entity.id.desc())
            .limit(120)
        )
        .unique()
        .all()
    )
    relations = list(
        session.scalars(
            select(EntityRelation)
            .where(EntityRelation.source_evidence_item_id.in_(evidence_ids))
            .options(
                selectinload(EntityRelation.source_entity),
                selectinload(EntityRelation.target_entity),
                selectinload(EntityRelation.source_evidence_item),
            )
            .order_by(EntityRelation.updated_at.desc(), EntityRelation.id.desc())
            .limit(200)
        )
        .unique()
        .all()
    )
    type_counter = Counter(entity.entity_type for entity in entities)
    relation_counter = Counter(relation.relation_type for relation in relations)
    ready = bool(entities and relations)
    if ready:
        summary = f"已从当前任务证据沉淀 {len(entities)} 个实体、{len(relations)} 条关系，可进入实体库和关系图谱复用。"
        actions = [{"label": "查看关系图谱", "view": "graph", "reason": "检查公司、文档、指标和风险事件之间的证据化关系。"}]
    else:
        summary = "任务证据已就绪，但尚未沉淀为实体关系记忆。建议先执行任务级沉淀，再进入关系分析。"
        actions = [{"label": "沉淀任务证据", "view": "tasks", "reason": "把任务证据池转成可复用的实体和关系记忆。"}]
    return {
        "task_id": task_id,
        "ready": ready,
        "source_evidence_count": len(evidence_items),
        "entity_count": len(entities),
        "relation_count": len(relations),
        "type_distribution": [{"name": key, "count": value} for key, value in type_counter.most_common()],
        "relation_distribution": [{"name": key, "count": value} for key, value in relation_counter.most_common()],
        "sample_entities": [
            {
                "id": entity.id,
                "entity_type": entity.entity_type,
                "canonical_name": entity.canonical_name,
                "symbol": entity.symbol,
                "source_evidence_id": entity.source_evidence_item.evidence_id if entity.source_evidence_item else None,
            }
            for entity in entities[:8]
        ],
        "sample_relations": [
            {
                "id": relation.id,
                "relation_type": relation.relation_type,
                "source": relation.source_entity.canonical_name,
                "target": relation.target_entity.canonical_name,
                "source_evidence_id": relation.source_evidence_item.evidence_id if relation.source_evidence_item else None,
            }
            for relation in relations[:8]
        ],
        "summary": summary,
        "recommended_actions": actions,
    }


def _build_stats(
    *,
    evidence: list[dict[str, Any]],
    facts: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    claims: list[dict[str, Any]],
) -> dict[str, Any]:
    verified_statuses = {"supported", "verified", "passed"}
    failed_statuses = {"failed", "unsupported", "missing_evidence", "numeric_mismatch"}
    verified_claims = [item for item in claims if str(item.get("verification_status")) in verified_statuses]
    failed_claims = [item for item in claims if str(item.get("verification_status")) in failed_statuses]
    pending_claims = [item for item in claims if str(item.get("review_status") or "pending") == "pending"]
    evidence_linked_claims = [item for item in claims if int(item.get("evidence_count") or 0) > 0]
    citation_failed = [item for item in claims if str(item.get("citation_check_status")) == "failed"]
    numeric_failed = [item for item in claims if str(item.get("numeric_check_status")) == "failed"]
    official_evidence = [
        item
        for item in evidence
        if str(item.get("trust_level") or "").lower() in {"official", "primary"}
        or any(token in str(item.get("source_type") or "").lower() for token in ("sec", "edgar", "cninfo", "hkex", "filing"))
    ]
    high_signals = [item for item in signals if str(item.get("severity")) == "high"]
    source_counter = Counter(str(item.get("source_type") or "unknown") for item in evidence)
    signal_counter = Counter(str(item.get("category") or "research") for item in signals)
    return {
        "evidence_count": len(evidence),
        "official_evidence_count": len(official_evidence),
        "financial_fact_count": len(facts),
        "investment_signal_count": len(signals),
        "high_severity_signal_count": len(high_signals),
        "claim_count": len(claims),
        "verified_claim_count": len(verified_claims),
        "failed_claim_count": len(failed_claims),
        "pending_review_count": len(pending_claims),
        "evidence_linked_claim_count": len(evidence_linked_claims),
        "citation_failed_count": len(citation_failed),
        "numeric_failed_count": len(numeric_failed),
        "citation_coverage_rate": _ratio(len(evidence_linked_claims), len(claims)),
        "claim_verified_rate": _ratio(len(verified_claims), len(claims)),
        "official_evidence_rate": _ratio(len(official_evidence), len(evidence)),
        "source_distribution": [{"name": key, "count": value} for key, value in source_counter.most_common()],
        "signal_distribution": [{"name": key, "count": value} for key, value in signal_counter.most_common()],
    }


def _build_signal_summary(signals: list[dict[str, Any]]) -> dict[str, Any]:
    top_signals = _top_signals(signals)[:5]
    high_priority = [item for item in signals if str(item.get("severity")) == "high"]
    in_context = [item for item in signals if str(item.get("status")) == "in_context"]
    positive = [item for item in signals if str(item.get("direction")) == "positive"]
    negative = [item for item in signals if str(item.get("direction")) == "negative"]
    neutral = [item for item in signals if str(item.get("direction")) not in {"positive", "negative"}]
    evidence_bound = [item for item in signals if item.get("evidence") or item.get("source_fact")]
    if not signals:
        return {
            "ready": False,
            "signal_count": 0,
            "high_priority_count": 0,
            "in_context_count": 0,
            "positive_count": 0,
            "negative_count": 0,
            "neutral_count": 0,
            "evidence_bound_count": 0,
            "brief": "当前任务还没有形成投资线索。建议先导入财务事实，并补齐官方或一手证据。",
            "top_signals": [],
            "recommended_actions": [
                {"label": "生成当前任务线索", "view": "tasks", "reason": "根据当前任务公司、期间、财务事实和证据缺口运行规则线索。"},
                {"label": "导入财务事实", "view": "facts", "reason": "线索规则依赖结构化指标、口径和证据绑定。"},
            ],
        }
    action_texts = [str(item.get("recommended_action") or "") for item in top_signals if item.get("recommended_action")]
    if high_priority:
        brief = f"已识别 {len(signals)} 条投资线索，其中 {len(high_priority)} 条需要优先复核；重点处理 {top_signals[0].get('title') or '高优先级线索'}。"
    elif positive and not negative:
        brief = f"已识别 {len(signals)} 条线索，当前以机会跟踪为主，仍需证据和主张复核后才能进入研报结论。"
    else:
        brief = f"已识别 {len(signals)} 条线索，建议按证据绑定、优先级和是否进入任务上下文逐条复核。"
    return {
        "ready": True,
        "signal_count": len(signals),
        "high_priority_count": len(high_priority),
        "in_context_count": len(in_context),
        "positive_count": len(positive),
        "negative_count": len(negative),
        "neutral_count": len(neutral),
        "evidence_bound_count": len(evidence_bound),
        "brief": brief,
        "top_signals": [
            {
                "id": item.get("id"),
                "signal_id": item.get("signal_id"),
                "title": item.get("title"),
                "summary": item.get("summary"),
                "severity": item.get("severity"),
                "direction": item.get("direction"),
                "status": item.get("status"),
                "priority_label": item.get("priority_label"),
                "recommended_action": item.get("recommended_action"),
                "decision_use": item.get("decision_use"),
                "evidence": item.get("evidence"),
                "source_fact": item.get("source_fact"),
            }
            for item in top_signals
        ],
        "recommended_actions": [
            {"label": "加入研报上下文", "view": "signals", "reason": "把已复核线索写入任务上下文，后续报告生成才能引用。"},
            {"label": "补齐线索证据", "view": "evidence", "reason": action_texts[0] if action_texts else "高优先级线索需要绑定可追溯证据。"},
        ],
    }


def _build_quality_proof(
    *,
    task_payload: dict[str, Any],
    stats: dict[str, Any],
    claims: list[dict[str, Any]],
    citation_usage: dict[str, Any],
    retrieval_coverage: dict[str, Any],
) -> dict[str, Any]:
    diagnostics = task_payload.get("quality_diagnostics") if isinstance(task_payload.get("quality_diagnostics"), dict) else {}
    failed_claims = [
        {
            "id": item.get("id"),
            "section_name": item.get("section_name"),
            "claim_text": item.get("claim_text"),
            "verification_status": item.get("verification_status"),
            "numeric_check_status": item.get("numeric_check_status"),
            "citation_check_status": item.get("citation_check_status"),
            "review_status": item.get("review_status"),
        }
        for item in claims
        if str(item.get("verification_status")) not in {"supported", "verified", "passed"}
        or str(item.get("citation_check_status")) == "failed"
        or str(item.get("numeric_check_status")) == "failed"
    ][:12]
    checks = [
        _check_item(
            key="evidence_binding",
            title="证据绑定",
            passed=stats["evidence_count"] > 0 and _rate_at_least(stats["citation_coverage_rate"], 0.8),
            value=stats["citation_coverage_rate"],
            description="主张需要绑定可追溯证据，低覆盖率会降低研报可信度。",
        ),
        _check_item(
            key="claim_verification",
            title="主张校验",
            passed=stats["claim_count"] == 0 or _rate_at_least(stats["claim_verified_rate"], 0.7),
            value=stats["claim_verified_rate"],
            description="关键主张应通过证据、数字和引用校验。",
        ),
        _check_item(
            key="numeric_consistency",
            title="数字一致性",
            passed=stats["numeric_failed_count"] == 0,
            value=stats["numeric_failed_count"],
            description="数字冲突需要回到财务事实和原始证据修正。",
        ),
        _check_item(
            key="citation_consistency",
            title="引用一致性",
            passed=stats["citation_failed_count"] == 0,
            value=stats["citation_failed_count"],
            description="引用缺失或引用无法命中证据时，需要补证据或降级表述。",
        ),
        _check_item(
            key="citation_usage",
            title="报告引用使用",
            passed=bool(citation_usage.get("ready")),
            value=citation_usage.get("claim_usage_rate"),
            description=str(citation_usage.get("summary") or "检查已绑定证据是否真正进入报告正文。"),
        ),
        _check_item(
            key="source_coverage",
            title="来源覆盖",
            passed=bool(retrieval_coverage.get("quality_ready")),
            value=retrieval_coverage.get("returned_count", 0),
            description=str(retrieval_coverage.get("summary") or "检查任务是否已命中必要官方或一手来源。"),
        ),
    ]
    return {
        "delivery_pass": diagnostics.get("delivery_pass"),
        "quality_score": task_payload.get("quality_score") if task_payload.get("quality_score") is not None else diagnostics.get("quality_score"),
        "objective_pass": diagnostics.get("objective_pass"),
        "llm_review_pass": diagnostics.get("llm_review_pass"),
        "top_issues": diagnostics.get("top_issues") or [],
        "failure_categories": diagnostics.get("failure_categories") or {},
        "checks": checks,
        "failed_claims": failed_claims,
        "retrieval_coverage": retrieval_coverage,
        "explanation": _quality_explanation(diagnostics=diagnostics, stats=stats, checks=checks),
    }


def _build_argument_chain(
    *,
    company_name: str,
    symbol: str,
    period: str,
    facts: list[dict[str, Any]],
    signals: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    fact_nodes = _top_facts(facts)
    signal_nodes = _top_signals(signals)
    claim_nodes = _top_claims(claims)
    evidence_nodes = _top_evidence(evidence)
    for item in evidence_nodes:
        nodes.append({"id": f"evidence:{item['evidence_id']}", "type": "evidence", "title": item.get("title") or item["evidence_id"], "payload": item})
    for item in fact_nodes:
        nodes.append({"id": f"fact:{item['id']}", "type": "fact", "title": _fact_title(item), "payload": item})
        ev = (item.get("evidence") or {}).get("evidence_id")
        if ev:
            edges.append({"from": f"evidence:{ev}", "to": f"fact:{item['id']}", "label": "支持事实"})
    for item in signal_nodes:
        nodes.append({"id": f"signal:{item['id']}", "type": "signal", "title": item.get("title") or item.get("signal_id"), "payload": item})
        fact = item.get("source_fact") or {}
        if fact.get("id"):
            edges.append({"from": f"fact:{fact['id']}", "to": f"signal:{item['id']}", "label": "触发线索"})
        ev = (item.get("evidence") or {}).get("evidence_id")
        if ev:
            edges.append({"from": f"evidence:{ev}", "to": f"signal:{item['id']}", "label": "提供证据"})
    for item in claim_nodes:
        nodes.append({"id": f"claim:{item['id']}", "type": "claim", "title": item.get("claim_text") or f"主张 {item['id']}", "payload": item})
        for ev in item.get("evidence") or []:
            evidence_id = ev.get("evidence_id")
            if evidence_id:
                edges.append({"from": f"evidence:{evidence_id}", "to": f"claim:{item['id']}", "label": "支撑主张"})
        if signal_nodes:
            edges.append({"from": f"signal:{signal_nodes[0]['id']}", "to": f"claim:{item['id']}", "label": "进入研报观点"})
    completeness = {
        "has_evidence": bool(evidence_nodes),
        "has_facts": bool(fact_nodes),
        "has_signals": bool(signal_nodes),
        "has_claims": bool(claim_nodes),
        "edge_count": len(edges),
    }
    return {
        "title": f"{company_name or symbol} {period} 投资逻辑链",
        "summary": _argument_summary(company_name=company_name, symbol=symbol, period=period, nodes=nodes, edges=edges),
        "nodes": nodes,
        "edges": edges,
        "completeness": completeness,
    }


def _build_risk_chain(
    *,
    company_name: str,
    symbol: str,
    period: str,
    signals: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    risk_signals = [
        item
        for item in signals
        if str(item.get("direction")) == "negative"
        or str(item.get("severity")) == "high"
        or str(item.get("category")) in {"cashflow", "source_gap", "data_quality", "valuation"}
    ]
    if not risk_signals:
        risk_signals = signals[:3]
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    root_id = f"company:{symbol or company_name}"
    nodes.append({"id": root_id, "type": "company", "title": company_name or symbol, "payload": {"symbol": symbol, "period": period}})
    for signal in risk_signals[:6]:
        sid = f"risk:{signal['id']}"
        nodes.append({"id": sid, "type": "risk", "title": signal.get("title") or signal.get("signal_id"), "payload": signal})
        edges.append({"from": root_id, "to": sid, "label": "暴露风险"})
        ev = (signal.get("evidence") or {}).get("evidence_id")
        if ev:
            ev_node = f"evidence:{ev}"
            if not any(node["id"] == ev_node for node in nodes):
                match = next((item for item in evidence if item.get("evidence_id") == ev), {"evidence_id": ev, "title": ev})
                nodes.append({"id": ev_node, "type": "evidence", "title": match.get("title") or ev, "payload": match})
            edges.append({"from": ev_node, "to": sid, "label": "风险证据"})
    risk_claims = [
        item
        for item in claims
        if "risk" in str(item.get("claim_type") or "").lower()
        or "风险" in str(item.get("claim_text") or "")
        or str(item.get("verification_status")) not in {"supported", "verified", "passed"}
    ][:5]
    for claim in risk_claims:
        cid = f"claim:{claim['id']}"
        nodes.append({"id": cid, "type": "claim", "title": claim.get("claim_text") or f"主张 {claim['id']}", "payload": claim})
        if risk_signals:
            edges.append({"from": f"risk:{risk_signals[0]['id']}", "to": cid, "label": "影响表述"})
    return {
        "title": f"{company_name or symbol} {period} 风险传导链",
        "summary": _risk_summary(risk_signals=risk_signals, claims=risk_claims),
        "nodes": nodes,
        "edges": edges,
        "risk_count": len(risk_signals),
    }


def _build_narrative(*, task_payload: dict[str, Any], stats: dict[str, Any], entity_memory: dict[str, Any]) -> list[dict[str, Any]]:
    status = str(task_payload.get("status") or "")
    return [
        {
            "stage": "数据进入",
            "status": "done" if stats["evidence_count"] > 0 else "pending",
            "description": f"已关联 {stats['evidence_count']} 条证据，其中官方或一手证据 {stats['official_evidence_count']} 条。",
        },
        {
            "stage": "记忆沉淀",
            "status": "done" if entity_memory.get("ready") else "pending",
            "description": f"已沉淀 {entity_memory.get('entity_count', 0)} 个实体、{entity_memory.get('relation_count', 0)} 条关系，来源证据 {entity_memory.get('source_evidence_count', 0)} 条。",
        },
        {
            "stage": "结构化处理",
            "status": "done" if stats["financial_fact_count"] > 0 else "pending",
            "description": f"已沉淀 {stats['financial_fact_count']} 条财务事实，用于指标、估值和风险检查。",
        },
        {
            "stage": "线索发现",
            "status": "done" if stats["investment_signal_count"] > 0 else "pending",
            "description": f"已生成 {stats['investment_signal_count']} 条投资线索，高优先级 {stats['high_severity_signal_count']} 条。",
        },
        {
            "stage": "主张复核",
            "status": "done" if stats["pending_review_count"] == 0 and stats["claim_count"] > 0 else "pending",
            "description": f"已校验 {stats['verified_claim_count']} / {stats['claim_count']} 条主张，待人工复核 {stats['pending_review_count']} 条。",
        },
        {
            "stage": "报告输出",
            "status": "done" if status == "completed" else ("failed" if status in {"failed", "quality_failed"} else "pending"),
            "description": "报告通过质量门禁后，可进入导出中心生成正式交付包。",
        },
    ]


def _recommended_actions(
    *,
    task_payload: dict[str, Any],
    stats: dict[str, Any],
    entity_memory: dict[str, Any],
    quality_proof: dict[str, Any],
    retrieval_coverage: dict[str, Any],
    argument_chain: dict[str, Any],
    risk_chain: dict[str, Any],
) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    missing_sources = list(retrieval_coverage.get("missing_sources") or [])
    if stats["evidence_count"] == 0:
        actions.append({"label": "补充证据", "view": "evidence", "reason": "当前任务没有可追溯证据。"})
    elif missing_sources:
        actions.append(
            {
                "label": "补齐关键来源",
                "view": "datasources",
                "reason": "当前任务证据已命中，但缺少必要官方或一手来源：" + "、".join(_source_label(item) for item in missing_sources) + "。",
            }
        )
    if stats["financial_fact_count"] == 0:
        actions.append({"label": "导入财务事实", "view": "facts", "reason": "缺少结构化财务事实会影响数字分析。"})
    if stats["evidence_count"] > 0 and not entity_memory.get("ready"):
        actions.append({"label": "沉淀结构化记忆", "view": "tasks", "reason": "任务证据尚未形成可复用的实体关系记忆。"})
    if stats["investment_signal_count"] == 0:
        actions.append({"label": "生成投资线索", "view": "signals", "reason": "尚未形成风险或机会线索。"})
    if stats["pending_review_count"] > 0:
        actions.append({"label": "复核主张", "view": "claims", "reason": f"仍有 {stats['pending_review_count']} 条主张待人工复核。"})
    if quality_proof.get("delivery_pass") is False:
        actions.append({"label": "查看质量问题", "view": "claims", "reason": "质量门禁未通过，需要先处理阻塞项。"})
    if not argument_chain.get("edges"):
        actions.append({"label": "补全论证链", "view": "graph", "reason": "事实、线索和主张尚未形成可解释链路。"})
    if int(risk_chain.get("risk_count") or 0) == 0:
        actions.append({"label": "检查风险线索", "view": "signals", "reason": "未识别风险传导节点。"})
    if str(task_payload.get("status")) == "queued":
        actions.insert(0, {"label": "启动任务", "view": "tasks", "reason": "任务仍在排队，可以启动生成。"})
    return actions[:6]


def _load_citation_artifacts(task_payload: dict[str, Any]) -> dict[str, Any]:
    metadata = task_payload.get("metadata") if isinstance(task_payload.get("metadata"), dict) else {}
    output_dir = _path_from_metadata(metadata.get("output_dir"))
    report_dir = _path_from_metadata(metadata.get("report_dir"))
    citations = _read_json_list(output_dir / "citations.json") if output_dir is not None else []
    report_text = _read_text(report_dir / "report.md") if report_dir is not None else ""
    return {"citations": citations, "report_text": report_text}


def _build_citation_usage(
    *,
    claims: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    report_text: str,
) -> dict[str, Any]:
    normalized_citations = [_normalize_citation(item, report_text=report_text) for item in citations if isinstance(item, dict)]
    used_citations = [item for item in normalized_citations if item["used"]]
    unused_citations = [item for item in normalized_citations if not item["used"]]
    traceable_claims = [item for item in claims if int(item.get("evidence_count") or 0) > 0]
    claims_without_used_citation: list[dict[str, Any]] = []
    used_claim_count = 0
    for claim in traceable_claims:
        if _claim_has_used_citation(claim, normalized_citations):
            used_claim_count += 1
            continue
        claims_without_used_citation.append(
            {
                "id": claim.get("id"),
                "section_name": claim.get("section_name"),
                "claim_text": claim.get("claim_text"),
                "evidence_ids": _claim_evidence_ids(claim),
            }
        )
    claim_usage_rate = _ratio(used_claim_count, len(traceable_claims))
    citation_usage_rate = _ratio(len(used_citations), len(normalized_citations))
    status = _citation_usage_status(
        claim_count=len(claims),
        citation_count=len(normalized_citations),
        traceable_claim_count=len(traceable_claims),
        claims_without_used_citation=claims_without_used_citation,
    )
    recommended_actions = _citation_usage_actions(status=status, claims_without_used_citation=claims_without_used_citation)
    ready = status == "ready" and _rate_at_least(claim_usage_rate, 0.8)
    return {
        "status": status,
        "ready": ready,
        "summary": _citation_usage_summary(
            status=status,
            traceable_claim_count=len(traceable_claims),
            used_claim_count=used_claim_count,
            unused_citation_count=len(unused_citations),
        ),
        "citation_count": len(normalized_citations),
        "used_citation_count": len(used_citations),
        "unused_citation_count": len(unused_citations),
        "claim_count": len(claims),
        "traceable_claim_count": len(traceable_claims),
        "used_claim_count": used_claim_count,
        "claim_usage_rate": claim_usage_rate,
        "citation_usage_rate": citation_usage_rate,
        "unused_citations": unused_citations[:8],
        "claims_without_used_citation": claims_without_used_citation[:8],
        "recommended_actions": recommended_actions,
    }


def _normalize_citation(item: dict[str, Any], *, report_text: str) -> dict[str, Any]:
    evidence_id = str(item.get("evidence_id") or "").strip()
    claim_ids = [str(value) for value in item.get("claim_ids", []) if str(value)] if isinstance(item.get("claim_ids"), list) else []
    explicit_used = item.get("used_in_report") is True
    body_used = _citation_marker_in_report(evidence_id, report_text)
    used = explicit_used and (body_used if report_text else True)
    return {
        "citation_id": item.get("citation_id"),
        "evidence_id": evidence_id,
        "claim_ids": claim_ids,
        "used": used,
        "explicit_used": explicit_used,
        "body_used": body_used,
        "title": item.get("title") or evidence_id,
        "source_type": item.get("source_type"),
    }


def _claim_has_used_citation(claim: dict[str, Any], citations: list[dict[str, Any]]) -> bool:
    aliases = _claim_aliases(claim)
    evidence_ids = set(_claim_evidence_ids(claim))
    if not evidence_ids:
        return False
    for citation in citations:
        if not citation.get("used") or citation.get("evidence_id") not in evidence_ids:
            continue
        citation_claim_ids = set(citation.get("claim_ids") or [])
        if not citation_claim_ids or citation_claim_ids.intersection(aliases):
            return True
    return False


def _claim_aliases(claim: dict[str, Any]) -> set[str]:
    aliases = {str(claim.get("id"))}
    metadata = claim.get("metadata") if isinstance(claim.get("metadata"), dict) else {}
    for key in ("original_claim_id", "claim_id", "id"):
        value = metadata.get(key)
        if value:
            aliases.add(str(value))
    return {item for item in aliases if item and item != "None"}


def _claim_evidence_ids(claim: dict[str, Any]) -> list[str]:
    rows = claim.get("evidence") if isinstance(claim.get("evidence"), list) else []
    ids: list[str] = []
    for row in rows:
        evidence = row.get("evidence") if isinstance(row, dict) and isinstance(row.get("evidence"), dict) else row
        evidence_id = evidence.get("evidence_id") if isinstance(evidence, dict) else None
        if evidence_id:
            ids.append(str(evidence_id))
    metadata = claim.get("metadata") if isinstance(claim.get("metadata"), dict) else {}
    for evidence_id in metadata.get("evidence_ids", []) if isinstance(metadata.get("evidence_ids"), list) else []:
        if str(evidence_id) and str(evidence_id) not in ids:
            ids.append(str(evidence_id))
    return ids


def _citation_usage_status(
    *,
    claim_count: int,
    citation_count: int,
    traceable_claim_count: int,
    claims_without_used_citation: list[dict[str, Any]],
) -> str:
    if claim_count <= 0:
        return "no_claims"
    if traceable_claim_count <= 0:
        return "no_traceable_claims"
    if citation_count <= 0:
        return "no_citations"
    if claims_without_used_citation:
        return "citation_gap"
    return "ready"


def _citation_usage_summary(
    *,
    status: str,
    traceable_claim_count: int,
    used_claim_count: int,
    unused_citation_count: int,
) -> str:
    if status == "ready":
        return f"已确认 {used_claim_count} / {traceable_claim_count} 条可追溯主张的证据引用进入报告正文。"
    if status == "no_claims":
        return "尚未导入研报主张，无法检查报告正文是否使用了证据引用。"
    if status == "no_traceable_claims":
        return "当前主张未绑定证据，需要先完成 Claim-Evidence 绑定。"
    if status == "no_citations":
        return "未找到引用清单，无法证明报告正文使用了哪些证据。"
    return f"仍有 {traceable_claim_count - used_claim_count} 条可追溯主张没有在报告正文找到已使用引用，另有 {unused_citation_count} 条引用未进入正文。"


def _citation_usage_actions(*, status: str, claims_without_used_citation: list[dict[str, Any]]) -> list[dict[str, str]]:
    if status == "ready":
        return [{"label": "抽查报告引用", "view": "export", "reason": "引用闭环已形成，导出前建议抽查关键段落。"}]
    if status in {"no_claims", "no_traceable_claims"}:
        return [{"label": "进入主张复核", "view": "claims", "reason": "先补齐主张和证据绑定，再检查报告正文引用。"}]
    if status == "no_citations":
        return [{"label": "重新生成引用清单", "view": "tasks", "reason": "当前任务缺少引用产物，需要重新运行或导入产物。"}]
    first = claims_without_used_citation[0] if claims_without_used_citation else {}
    reason = str(first.get("claim_text") or "部分主张没有进入报告正文引用。")
    return [
        {"label": "复核缺引用主张", "view": "claims", "reason": reason},
        {"label": "重新生成报告", "view": "tasks", "reason": "将缺失引用的主张重新写入报告正文。"},
    ]


def _citation_marker_in_report(evidence_id: str, report_text: str) -> bool:
    if not evidence_id or not report_text:
        return False
    return f"[{evidence_id}]" in report_text or evidence_id in report_text


def _path_from_metadata(value: Any) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    return Path(text)


def _read_json_list(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("citations", "items", "records"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [item for item in rows if isinstance(item, dict)]
    return []


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _retrieval_mode(*, candidate_payloads: list[dict[str, Any]], evidence_payloads: list[dict[str, Any]]) -> str:
    if not candidate_payloads:
        return "no_candidates"
    if not evidence_payloads:
        return "no_hits"
    return "task_evidence"


def _build_retrieval_diagnostics(
    *,
    task_payload: dict[str, Any],
    company_name: str,
    symbol: str,
    period: str,
    candidate_payloads: list[dict[str, Any]],
    evidence_payloads: list[dict[str, Any]],
    retrieval_coverage: dict[str, Any],
) -> dict[str, Any]:
    metadata = task_payload.get("metadata") if isinstance(task_payload.get("metadata"), dict) else {}
    gate = metadata.get("pre_generation_evidence_gate") if isinstance(metadata.get("pre_generation_evidence_gate"), dict) else {}
    gaps = list(retrieval_coverage.get("gaps") or [])
    failure_reason = _retrieval_failure_reason(retrieval_coverage)
    stage = _retrieval_stage(retrieval_coverage)
    actions = _retrieval_diagnostic_actions(retrieval_coverage)
    query = {
        "company_name": company_name,
        "symbol": symbol,
        "period": period,
        "data_source_scope": metadata.get("data_source_scope") or "official_first",
        "required_sources": retrieval_coverage.get("required_sources") or [],
    }
    return {
        "stage": stage,
        "failure_reason": failure_reason,
        "summary": _retrieval_diagnostic_summary(
            stage=stage,
            failure_reason=failure_reason,
            retrieval_coverage=retrieval_coverage,
            gate=gate,
        ),
        "query": query,
        "candidate_count": len(candidate_payloads),
        "returned_count": len(evidence_payloads),
        "candidate_sources": retrieval_coverage.get("candidate_sources") or [],
        "returned_sources": retrieval_coverage.get("returned_sources") or [],
        "required_sources": retrieval_coverage.get("required_sources") or [],
        "missing_sources": retrieval_coverage.get("missing_sources") or [],
        "candidate_examples": _evidence_examples(candidate_payloads),
        "returned_examples": _evidence_examples(evidence_payloads),
        "gaps": gaps,
        "recommended_actions": actions,
        "pre_generation_gate": {
            "status": gate.get("status"),
            "blocked": bool(gate.get("blocked")) if gate else False,
            "summary": gate.get("summary"),
        }
        if gate
        else None,
    }


def _retrieval_stage(coverage: dict[str, Any]) -> str:
    if int(coverage.get("candidate_count") or 0) <= 0:
        return "no_data"
    if int(coverage.get("returned_count") or 0) <= 0:
        return "no_hits"
    if coverage.get("missing_sources"):
        return "source_gap"
    return "ready"


def _retrieval_failure_reason(coverage: dict[str, Any]) -> str:
    stage = _retrieval_stage(coverage)
    if stage == "ready":
        return ""
    if stage == "no_data":
        return "no_candidates"
    if stage == "no_hits":
        return "period_or_query_mismatch"
    if stage == "source_gap":
        return "missing_required_source"
    return "retrieval_gap"


def _retrieval_diagnostic_summary(
    *,
    stage: str,
    failure_reason: str,
    retrieval_coverage: dict[str, Any],
    gate: dict[str, Any],
) -> str:
    if gate.get("blocked"):
        return str(gate.get("summary") or "生成已暂停：证据覆盖不足。")
    if stage == "ready":
        return "当前任务已命中必要证据来源，可以进入主张复核和质量检查。"
    if failure_reason == "no_candidates":
        return "当前任务没有公司或任务相关的候选证据，需要先采集或手动导入资料。"
    if failure_reason == "period_or_query_mismatch":
        return "已有公司相关资料，但与当前查询期间或任务条件没有形成有效命中。"
    if failure_reason == "missing_required_source":
        missing = "、".join(_source_label(item) for item in retrieval_coverage.get("missing_sources") or [])
        return f"已有可用证据，但仍缺少关键权威来源：{missing}。"
    return str(retrieval_coverage.get("summary") or "证据召回存在缺口。")


def _retrieval_diagnostic_actions(coverage: dict[str, Any]) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    for gap in coverage.get("gaps") or []:
        gap_type = str(gap.get("type") or "")
        if gap_type == "no_candidates":
            actions.append({"label": "创建采集批次", "view": "ingestion", "reason": str(gap.get("description") or "")})
            actions.append({"label": "手动导入资料", "view": "manual", "reason": "如果已有年报或公告文件，可先手动导入形成证据。"})
        elif gap_type == "no_hits":
            actions.append({"label": "核对证据库", "view": "evidence", "reason": str(gap.get("description") or "")})
        elif gap_type == "source_gap":
            actions.append({"label": "检查数据源配置", "view": "datasources", "reason": str(gap.get("description") or "")})
            actions.append({"label": "补采集权威来源", "view": "ingestion", "reason": "为缺失来源创建采集批次，完成后回到任务重新检查。"})
        elif gap_type == "fusion_degraded":
            actions.append({"label": "补充更具体资料", "view": "manual", "reason": str(gap.get("description") or "")})
    if not actions:
        actions.append({"label": "查看证据库", "view": "evidence", "reason": "证据已命中，建议抽查原文和引用链。"})
    return _dedupe_actions(actions)[:4]


def _evidence_examples(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    for item in items[:5]:
        doc = item.get("document") if isinstance(item.get("document"), dict) else {}
        examples.append(
            {
                "evidence_id": item.get("evidence_id"),
                "title": item.get("title"),
                "source_type": item.get("source_type"),
                "trust_level": item.get("trust_level"),
                "report_period": doc.get("report_period") or item.get("metadata", {}).get("period"),
            }
        )
    return examples


def _dedupe_actions(actions: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    output: list[dict[str, str]] = []
    for item in actions:
        key = (str(item.get("label") or ""), str(item.get("view") or ""))
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _check_item(*, key: str, title: str, passed: bool, value: Any, description: str) -> dict[str, Any]:
    return {"key": key, "title": title, "passed": passed, "value": value, "description": description}


def _source_label(source_key: str) -> str:
    mapping = {
        "sec_edgar": "美国证监会披露",
        "cninfo": "巨潮资讯公告",
        "hkex": "港交所披露",
        "yahoo_finance": "雅虎财经",
        "local_pdf": "本地文档",
    }
    return mapping.get(str(source_key or ""), str(source_key or "关键来源"))


def _quality_explanation(*, diagnostics: dict[str, Any], stats: dict[str, Any], checks: list[dict[str, Any]]) -> str:
    if diagnostics.get("delivery_pass") is True:
        return "交付门禁已通过，仍建议在导出前抽查关键证据和人工复核记录。"
    failed_checks = [item["title"] for item in checks if item.get("passed") is False]
    if failed_checks:
        return "当前主要质量风险集中在：" + "、".join(failed_checks) + "。"
    if stats["claim_count"] == 0:
        return "尚未导入研报主张，无法证明报告结论是否已被证据支持。"
    return "质量门禁尚未形成完整结论，请结合证据、主张和人工复核继续检查。"


def _top_facts(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    preferred = ("营业收入", "收入", "revenue", "毛利率", "gross", "净利润", "现金流", "cash")
    deduped = _dedupe_dicts(
        facts,
        key_fn=lambda item: "|".join(
            [
                str(item.get("metric_name") or ""),
                str(item.get("period") or ""),
                str(item.get("value") or ""),
                str(item.get("unit") or item.get("currency") or ""),
            ]
        ),
    )
    return sorted(
        deduped,
        key=lambda item: (not any(token.lower() in str(item.get("metric_name") or "").lower() for token in preferred), -float(item.get("confidence") or 0.0)),
    )[:8]


def _top_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    severity_rank = {"high": 0, "medium": 1, "low": 2}
    deduped = _dedupe_dicts(
        signals,
        key_fn=lambda item: "|".join(
            [
                str(item.get("signal_type") or ""),
                str(item.get("category") or ""),
                str(item.get("title") or ""),
                str(item.get("summary") or ""),
            ]
        ),
    )
    return sorted(deduped, key=lambda item: (severity_rank.get(str(item.get("severity")), 3), -float(item.get("confidence") or 0.0)))[:8]


def _top_claims(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped = _dedupe_dicts(claims, key_fn=lambda item: str(item.get("claim_text") or item.get("id") or ""))
    return sorted(deduped, key=lambda item: (str(item.get("verification_status")) not in {"supported", "verified", "passed"}, -int(item.get("evidence_count") or 0)))[:8]


def _top_evidence(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped = _dedupe_dicts(evidence, key_fn=lambda item: str(item.get("evidence_id") or item.get("source_url") or item.get("title") or ""))
    return sorted(deduped, key=lambda item: (-int(item.get("claim_count") or 0), str(item.get("trust_level") or "")))[:8]


def _dedupe_dicts(items: list[dict[str, Any]], *, key_fn: Callable[[dict[str, Any]], str]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for item in items:
        key = key_fn(item)
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def _fact_title(item: dict[str, Any]) -> str:
    metric = item.get("metric_name") or "财务事实"
    value = item.get("value")
    unit = item.get("unit") or item.get("currency") or ""
    period = item.get("period") or ""
    return f"{metric} {value}{unit} {period}".strip()


def _argument_summary(*, company_name: str, symbol: str, period: str, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> str:
    if not nodes:
        return f"{company_name or symbol} {period} 尚未形成投资论证链。"
    return f"已将证据、财务事实、投资线索和研报主张组织为 {len(nodes)} 个节点、{len(edges)} 条关系，用于解释报告结论来源。"


def _risk_summary(*, risk_signals: list[dict[str, Any]], claims: list[dict[str, Any]]) -> str:
    if not risk_signals:
        return "当前任务尚未识别明确风险传导节点。"
    titles = [str(item.get("title") or item.get("signal_type")) for item in risk_signals[:3]]
    suffix = f"，并影响 {len(claims)} 条主张表述" if claims else ""
    return "主要风险线索包括：" + "、".join(titles) + suffix + "。"


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(float(numerator) / float(denominator), 4)


def _rate_at_least(value: Any, threshold: float) -> bool:
    try:
        return float(value) >= threshold
    except (TypeError, ValueError):
        return False


def _snippet(content: str | None, *, limit: int = 220) -> str:
    text = " ".join(str(content or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."
