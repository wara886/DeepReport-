"""Task-level analysis package for the workbench detail view."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from src.db.models import (
    ClaimEvidence,
    Company,
    EvidenceItem,
    FinancialFact,
    InvestmentSignal,
    ReportClaim,
    ReportTask,
)
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
            evidence_items = _evidence_for_task(session, task_id=task_id, symbol=symbol, company_id=company_id, period=period)
            facts = _facts_for_task(session, symbol=symbol, company_id=company_id, period=period)
            signals = _signals_for_task(session, task_id=task_id, symbol=symbol, company_id=company_id, period=period)

        evidence_payloads = [_serialize_evidence(item) for item in evidence_items[:40]]
        fact_payloads = [self.fact_service.serialize_fact(item) for item in facts[:40]]
        signal_payloads = [self.signal_service.serialize_signal(item) for item in signals[:30]]
        claim_payloads = [self.claim_service.serialize_claim(item, include_evidence=True) for item in claims[:50]]

        stats = _build_stats(
            evidence=evidence_payloads,
            facts=fact_payloads,
            signals=signal_payloads,
            claims=claim_payloads,
        )
        quality_proof = _build_quality_proof(task_payload=task_payload, stats=stats, claims=claim_payloads)
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
        narrative = _build_narrative(task_payload=task_payload, stats=stats)
        recommended_actions = _recommended_actions(
            task_payload=task_payload,
            stats=stats,
            quality_proof=quality_proof,
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


def _evidence_for_task(
    session: Session,
    *,
    task_id: str,
    symbol: str,
    company_id: int | None,
    period: str,
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
    items = list(session.scalars(stmt).unique().all())
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


def _build_quality_proof(
    *,
    task_payload: dict[str, Any],
    stats: dict[str, Any],
    claims: list[dict[str, Any]],
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


def _build_narrative(*, task_payload: dict[str, Any], stats: dict[str, Any]) -> list[dict[str, Any]]:
    status = str(task_payload.get("status") or "")
    return [
        {
            "stage": "数据进入",
            "status": "done" if stats["evidence_count"] > 0 else "pending",
            "description": f"已关联 {stats['evidence_count']} 条证据，其中官方或一手证据 {stats['official_evidence_count']} 条。",
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
    quality_proof: dict[str, Any],
    argument_chain: dict[str, Any],
    risk_chain: dict[str, Any],
) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    if stats["evidence_count"] == 0:
        actions.append({"label": "补充证据", "view": "evidence", "reason": "当前任务没有可追溯证据。"})
    if stats["financial_fact_count"] == 0:
        actions.append({"label": "导入财务事实", "view": "facts", "reason": "缺少结构化财务事实会影响数字分析。"})
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


def _check_item(*, key: str, title: str, passed: bool, value: Any, description: str) -> dict[str, Any]:
    return {"key": key, "title": title, "passed": passed, "value": value, "description": description}


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
