"""Investment signal rules and task-context binding for the P2 workbench."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
import re
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, selectinload

from src.db.models import Company, EvidenceItem, FinancialFact, InvestmentSignal, ReportTask


class InvestmentSignalNotFound(LookupError):
    """Raised when an investment signal cannot be found."""


class InvestmentSignalConflict(RuntimeError):
    """Raised when a signal operation cannot be applied."""


SIGNAL_TYPES = {
    "margin_decline",
    "cashflow_gap",
    "official_source_missing",
    "currency_mismatch",
    "valuation_blocked",
    "revenue_growth_acceleration",
}
SOURCE_OFFICIAL_HINTS = ("official", "sec", "edgar", "cninfo", "hkex", "exchange", "filing", "announcement")


class InvestmentSignalService:
    """Generate and manage evidence-backed investment research signals."""

    def __init__(self, *, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    def generate_signals(
        self,
        *,
        company: str | None = None,
        period: str | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        """Run the P2.3 rule set and persist deterministic signal records."""

        with self.session_factory() as session:
            task = _get_task_optional(session, task_id)
            normalized_company = _optional_string(company)
            normalized_period = _optional_upper(period or (task.period if task else None))
            if task and not normalized_company:
                normalized_company = task.symbol

            facts = _facts_for_scope(session, company=normalized_company, period=None)
            scoped_facts = [
                fact
                for fact in facts
                if not normalized_period or _period_key(fact.period) <= _period_key(normalized_period)
            ]
            payloads: list[dict[str, Any]] = []
            payloads.extend(_margin_decline_signals(scoped_facts, period=normalized_period, task=task))
            payloads.extend(_cashflow_gap_signals(scoped_facts, period=normalized_period, task=task))
            payloads.extend(_currency_mismatch_signals(scoped_facts, period=normalized_period, task=task))
            payloads.extend(_valuation_blocked_signals(scoped_facts, period=normalized_period, task=task))
            payloads.extend(_revenue_growth_acceleration_signals(scoped_facts, period=normalized_period, task=task))
            payloads.extend(
                _official_source_missing_signals(
                    session,
                    facts=scoped_facts,
                    company=normalized_company,
                    period=normalized_period,
                    task=task,
                )
            )

            signals = [_upsert_signal(session, payload) for payload in payloads]
            session.commit()
            return {
                "items": [self.serialize_signal(item) for item in signals],
                "generated": len(signals),
                "rule_count": len(SIGNAL_TYPES),
            }

    def list_signals(
        self,
        *,
        company: str | None = None,
        period: str | None = None,
        signal_type: str | None = None,
        status: str | None = None,
        task_id: str | None = None,
        q: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit or 100), 300))
        with self.session_factory() as session:
            stmt = (
                select(InvestmentSignal)
                .options(
                    selectinload(InvestmentSignal.company),
                    selectinload(InvestmentSignal.evidence_item),
                    selectinload(InvestmentSignal.source_fact).selectinload(FinancialFact.evidence_item),
                    selectinload(InvestmentSignal.task),
                )
                .order_by(InvestmentSignal.updated_at.desc(), InvestmentSignal.id.desc())
                .limit(limit)
            )
            stmt = _apply_filters(
                stmt,
                company=company,
                period=period,
                signal_type=signal_type,
                status=status,
                task_id=task_id,
                q=q,
            )
            items = [self.serialize_signal(item) for item in session.scalars(stmt).unique().all()]
        return {"items": items, "total": len(items)}

    def get_signal(self, signal_ref: int | str) -> dict[str, Any]:
        with self.session_factory() as session:
            signal = _get_signal(session, signal_ref)
            return self.serialize_signal(signal)

    def add_to_report_context(self, signal_ref: int | str, task_id: str) -> dict[str, Any]:
        with self.session_factory() as session:
            signal = _get_signal(session, signal_ref)
            task = _get_task_required(session, task_id)
            metadata = dict(task.metadata_json or {})
            context_items = list(metadata.get("investment_signals") or [])
            compact = _compact_signal_context(signal)
            context_items = [item for item in context_items if str(item.get("signal_id")) != signal.signal_id]
            context_items.append(compact)
            metadata["investment_signals"] = context_items[-12:]
            task.metadata_json = metadata
            signal.task_id = task.task_id
            signal.status = "in_context"
            session.commit()
            return {"task": _serialize_task(task), "signal": self.serialize_signal(signal)}

    def serialize_signal(self, signal: InvestmentSignal) -> dict[str, Any]:
        evidence = signal.evidence_item or (signal.source_fact.evidence_item if signal.source_fact else None)
        recommended_action = _recommended_action(signal)
        decision_use = _decision_use(signal)
        return {
            "id": signal.id,
            "signal_id": signal.signal_id,
            "task_id": signal.task_id,
            "company_id": signal.company_id,
            "company": _serialize_company(signal.company),
            "signal_type": signal.signal_type,
            "category": signal.category,
            "title": signal.title,
            "summary": signal.summary,
            "severity": signal.severity,
            "direction": signal.direction,
            "confidence": signal.confidence,
            "priority_label": _priority_label(signal),
            "recommended_action": recommended_action,
            "decision_use": decision_use,
            "research_brief": _research_brief(signal, recommended_action=recommended_action, decision_use=decision_use),
            "status": signal.status,
            "period": signal.period,
            "source_rule": signal.source_rule,
            "evidence": _serialize_evidence(evidence),
            "source_fact": _serialize_fact(signal.source_fact),
            "metadata": signal.metadata_json or {},
            "created_at": _dt(signal.created_at),
            "updated_at": _dt(signal.updated_at),
        }


def _apply_filters(
    stmt: Select[tuple[InvestmentSignal]],
    *,
    company: str | None,
    period: str | None,
    signal_type: str | None,
    status: str | None,
    task_id: str | None,
    q: str | None,
) -> Select[tuple[InvestmentSignal]]:
    if company:
        needle = f"%{company.strip()}%"
        stmt = stmt.join(InvestmentSignal.company, isouter=True).where(
            or_(Company.name.ilike(needle), Company.symbol.ilike(needle))
        )
    if period:
        stmt = stmt.where(InvestmentSignal.period == period.strip().upper())
    if signal_type:
        normalized = _signal_type(signal_type)
        stmt = stmt.where(InvestmentSignal.signal_type == normalized)
    if status:
        stmt = stmt.where(InvestmentSignal.status == status.strip())
    if task_id:
        stmt = stmt.where(InvestmentSignal.task_id == task_id.strip())
    if q:
        needle = f"%{q.strip()}%"
        stmt = stmt.where(or_(InvestmentSignal.title.ilike(needle), InvestmentSignal.summary.ilike(needle)))
    return stmt


def _priority_label(signal: InvestmentSignal) -> str:
    if signal.status == "in_context":
        return "已进入研报上下文"
    if signal.severity == "high":
        return "优先复核"
    if signal.direction == "positive":
        return "机会跟踪"
    if signal.signal_type in {"official_source_missing", "currency_mismatch", "valuation_blocked"}:
        return "生成前处理"
    return "持续观察"


def _recommended_action(signal: InvestmentSignal) -> str:
    mapping = {
        "margin_decline": "复核毛利率、费用率和产品结构变化，并绑定官方披露证据。",
        "cashflow_gap": "核对经营现金流、回款、库存和资本开支，避免仅用利润口径下结论。",
        "official_source_missing": "补齐公告、年报、交易所披露或一手来源后再进入正式研报。",
        "currency_mismatch": "统一币种、单位和折算口径，处理后再进入估值或横向对比。",
        "valuation_blocked": "补充市值、股价、估值倍数或可比公司口径，估值章节保持阻塞说明。",
        "revenue_growth_acceleration": "继续核对收入拆分、订单和可持续性证据，避免把短期改善直接写成结论。",
    }
    return mapping.get(signal.signal_type, "补齐证据、复核口径后再写入研报主张。")


def _decision_use(signal: InvestmentSignal) -> str:
    if signal.signal_type in {"official_source_missing", "currency_mismatch", "valuation_blocked"}:
        return "用于判断研报生成是否需要暂停、降级或补充资料，不构成投资建议。"
    if signal.direction == "negative":
        return "用于风险提示、关键假设压力测试和人工复核优先级排序，不构成投资建议。"
    if signal.direction == "positive":
        return "用于机会线索跟踪和增长假设复核，不能直接作为投资建议。"
    return "用于研究流程分流和证据补齐，不构成投资建议。"


def _research_brief(signal: InvestmentSignal, *, recommended_action: str, decision_use: str) -> str:
    evidence_text = "已有证据绑定" if signal.evidence_item_id or signal.source_fact_id else "证据仍需补齐"
    return f"{signal.title}：{signal.summary} 当前优先级为{_priority_label(signal)}，{evidence_text}。建议动作：{recommended_action} {decision_use}"


def _upsert_signal(session: Session, payload: dict[str, Any]) -> InvestmentSignal:
    signal_type = _signal_type(payload.get("signal_type"))
    title = _optional_string(payload.get("title"))
    summary = _optional_string(payload.get("summary"))
    if not title or not summary:
        raise InvestmentSignalConflict("title and summary are required")
    company = payload.get("company")
    if company is not None and not isinstance(company, Company):
        company = None
    evidence = payload.get("evidence")
    if evidence is not None and not isinstance(evidence, EvidenceItem):
        evidence = None
    source_fact = payload.get("source_fact")
    if source_fact is not None and not isinstance(source_fact, FinancialFact):
        source_fact = None
    task = payload.get("task")
    if task is not None and not isinstance(task, ReportTask):
        task = None
    period = _optional_upper(payload.get("period"))
    signal_id = _optional_string(payload.get("signal_id")) or _signal_id(
        signal_type=signal_type,
        company=company,
        period=period,
        source_fact=source_fact,
        evidence=evidence,
        task=task,
        suffix=_optional_string(payload.get("suffix")),
    )
    signal = session.scalar(select(InvestmentSignal).where(InvestmentSignal.signal_id == signal_id))
    fields = {
        "task_id": task.task_id if task else _optional_string(payload.get("task_id")),
        "company_id": company.id if company else None,
        "evidence_item_id": evidence.id if evidence else None,
        "source_fact_id": source_fact.id if source_fact else None,
        "signal_type": signal_type,
        "category": _optional_string(payload.get("category")) or "research",
        "title": title,
        "summary": summary,
        "severity": _optional_string(payload.get("severity")) or "medium",
        "direction": _optional_string(payload.get("direction")) or "neutral",
        "confidence": _optional_float(payload.get("confidence"), default=0.7),
        "status": _optional_string(payload.get("status")) or "pending",
        "period": period,
        "source_rule": _optional_string(payload.get("source_rule")) or signal_type,
        "metadata_json": _dict_or_empty(payload.get("metadata")),
    }
    if signal is None:
        signal = InvestmentSignal(signal_id=signal_id, **fields)
        session.add(signal)
    else:
        for key, value in fields.items():
            setattr(signal, key, value)
    session.flush()
    return signal


def _margin_decline_signals(facts: list[FinancialFact], *, period: str | None, task: ReportTask | None) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for current, previous in _metric_pairs(facts, _is_margin_metric, period=period):
        change = _value_change(current, previous)
        if change >= -1.0:
            continue
        company = current.company or previous.company
        payloads.append(
            {
                "task": task,
                "company": company,
                "source_fact": current,
                "evidence": current.evidence_item or previous.evidence_item,
                "signal_type": "margin_decline",
                "category": "profitability",
                "title": "利润率下滑",
                "summary": f"{_company_name(company)} {_period_text(current.period)} {current.metric_name}较上一期下降 {abs(round(change, 2))} 个百分点，需要复核毛利、费用和产品结构变化。",
                "severity": "high" if change <= -3 else "medium",
                "direction": "negative",
                "confidence": _fact_confidence(current, previous),
                "period": current.period,
                "source_rule": "margin_decline",
                "metadata": {
                    "current_value": current.value,
                    "previous_value": previous.value,
                    "change": round(change, 4),
                    "boundary": "研究线索，不构成投资建议",
                },
            }
        )
    for fact in facts:
        metadata = fact.metadata_json or {}
        previous_value = _optional_float(metadata.get("previous_value") or metadata.get("prior_value"))
        if not _is_margin_metric(fact.metric_name) or previous_value is None:
            continue
        change = fact.value - previous_value
        if change >= -1.0:
            continue
        company = fact.company
        payloads.append(
            {
                "task": task,
                "company": company,
                "source_fact": fact,
                "evidence": fact.evidence_item,
                "signal_type": "margin_decline",
                "category": "profitability",
                "title": "利润率下滑",
                "summary": f"{_company_name(company)} {_period_text(fact.period)} {fact.metric_name}较对比期下降 {abs(round(change, 2))} 个百分点。",
                "severity": "high" if change <= -3 else "medium",
                "direction": "negative",
                "confidence": _fact_confidence(fact, None),
                "period": fact.period,
                "source_rule": "margin_decline",
                "metadata": {"current_value": fact.value, "previous_value": previous_value, "change": round(change, 4), "boundary": "研究线索，不构成投资建议"},
            }
        )
    return _dedupe_payloads(payloads)


def _cashflow_gap_signals(facts: list[FinancialFact], *, period: str | None, task: ReportTask | None) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    by_company_period = _group_by_company_period(facts)
    for (_, fact_period), grouped in by_company_period.items():
        if period and fact_period != period:
            continue
        cashflow = _best_fact(grouped, _is_cashflow_metric)
        profit = _best_fact(grouped, _is_profit_metric)
        if not cashflow or not profit:
            continue
        if cashflow.value < 0 < profit.value:
            company = cashflow.company or profit.company
            payloads.append(
                {
                    "task": task,
                    "company": company,
                    "source_fact": cashflow,
                    "evidence": cashflow.evidence_item or profit.evidence_item,
                    "signal_type": "cashflow_gap",
                    "category": "cashflow",
                    "title": "利润与现金流背离",
                    "summary": f"{_company_name(company)} {_period_text(fact_period)} {profit.metric_name}为正，但{cashflow.metric_name}为负，需要复核回款、库存和资本开支压力。",
                    "severity": "high",
                    "direction": "negative",
                    "confidence": _fact_confidence(cashflow, profit),
                    "period": fact_period,
                    "source_rule": "cashflow_gap",
                    "metadata": {
                        "cashflow_value": cashflow.value,
                        "profit_value": profit.value,
                        "boundary": "研究线索，不构成投资建议",
                    },
                }
            )
    return payloads


def _official_source_missing_signals(
    session: Session,
    *,
    facts: list[FinancialFact],
    company: str | None,
    period: str | None,
    task: ReportTask | None,
) -> list[dict[str, Any]]:
    if not (task or company or facts):
        return []
    company_obj = _scope_company(facts)
    if not company_obj and company:
        company_obj = _find_company(session, company)
    if _has_official_evidence(session, company=company_obj, company_text=company, period=period, task=task):
        return []
    title_company = _company_name(company_obj) if company_obj else (company or (task.symbol if task else "目标公司"))
    return [
        {
            "task": task,
            "company": company_obj,
            "signal_type": "official_source_missing",
            "category": "source_gap",
            "title": "官方来源缺口",
            "summary": f"{title_company} {_period_text(period)} 当前范围内未找到官方公告、交易所披露或一手来源绑定，生成研报前需要补齐可追溯证据。",
            "severity": "high",
            "direction": "neutral",
            "confidence": 0.75,
            "period": period,
            "source_rule": "official_source_missing",
            "metadata": {"task_id": task.task_id if task else None, "boundary": "研究线索，不构成投资建议"},
        }
    ]


def _currency_mismatch_signals(facts: list[FinancialFact], *, period: str | None, task: ReportTask | None) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    by_company_period = _group_by_company_period([fact for fact in facts if fact.metric_type == "money" or fact.currency])
    for (_, fact_period), grouped in by_company_period.items():
        if period and fact_period != period:
            continue
        currencies = sorted({fact.currency for fact in grouped if fact.currency})
        if len(currencies) < 2:
            continue
        source_fact = grouped[0]
        company = source_fact.company
        payloads.append(
            {
                "task": task,
                "company": company,
                "source_fact": source_fact,
                "evidence": source_fact.evidence_item,
                "signal_type": "currency_mismatch",
                "category": "data_quality",
                "title": "币种口径不一致",
                "summary": f"{_company_name(company)} {_period_text(fact_period)} 已入库金额事实同时出现 {'、'.join(currencies)}，需要统一币种和单位后再进入正式论证。",
                "severity": "medium",
                "direction": "neutral",
                "confidence": 0.85,
                "period": fact_period,
                "source_rule": "currency_mismatch",
                "metadata": {"currencies": currencies, "fact_count": len(grouped), "boundary": "研究线索，不构成投资建议"},
            }
        )
    return payloads


def _valuation_blocked_signals(facts: list[FinancialFact], *, period: str | None, task: ReportTask | None) -> list[dict[str, Any]]:
    if not facts:
        return []
    current = [fact for fact in facts if not period or fact.period == period]
    scoped = current or facts
    if any(_is_valuation_metric(fact.metric_name) for fact in scoped):
        return []
    company = _scope_company(scoped)
    source_fact = scoped[0]
    return [
        {
            "task": task,
            "company": company,
            "source_fact": source_fact,
            "evidence": source_fact.evidence_item,
            "signal_type": "valuation_blocked",
            "category": "valuation",
            "title": "估值分析缺少必要事实",
            "summary": f"{_company_name(company)} {_period_text(period or source_fact.period)} 已有财务事实，但未发现估值倍数、市值或股价等估值口径，估值章节应保持阻塞或降级说明。",
            "severity": "medium",
            "direction": "neutral",
            "confidence": 0.7,
            "period": period or source_fact.period,
            "source_rule": "valuation_blocked",
            "metadata": {"available_fact_count": len(scoped), "boundary": "研究线索，不构成投资建议"},
        }
    ]


def _revenue_growth_acceleration_signals(
    facts: list[FinancialFact],
    *,
    period: str | None,
    task: ReportTask | None,
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for current, previous, older in _metric_triples(facts, _is_revenue_metric, period=period):
        if older.value == 0 or previous.value == 0:
            continue
        previous_growth = (previous.value - older.value) / abs(older.value)
        current_growth = (current.value - previous.value) / abs(previous.value)
        acceleration = current_growth - previous_growth
        if acceleration < 0.05 or current_growth <= 0:
            continue
        company = current.company or previous.company
        payloads.append(
            {
                "task": task,
                "company": company,
                "source_fact": current,
                "evidence": current.evidence_item or previous.evidence_item,
                "signal_type": "revenue_growth_acceleration",
                "category": "growth",
                "title": "收入增速改善",
                "summary": f"{_company_name(company)} {_period_text(current.period)} 收入增速较上一阶段提高 {round(acceleration * 100, 2)} 个百分点，可作为增长改善线索继续复核。",
                "severity": "medium",
                "direction": "positive",
                "confidence": _fact_confidence(current, previous),
                "period": current.period,
                "source_rule": "revenue_growth_acceleration",
                "metadata": {
                    "current_growth": round(current_growth, 6),
                    "previous_growth": round(previous_growth, 6),
                    "acceleration": round(acceleration, 6),
                    "boundary": "研究线索，不构成投资建议",
                },
            }
        )
    for fact in facts:
        metadata = fact.metadata_json or {}
        current_growth = _optional_float(metadata.get("growth_rate") or metadata.get("current_growth"))
        previous_growth = _optional_float(metadata.get("previous_growth_rate") or metadata.get("previous_growth"))
        if not _is_revenue_metric(fact.metric_name) or current_growth is None or previous_growth is None:
            continue
        acceleration = current_growth - previous_growth
        if acceleration < 0.05 or current_growth <= 0:
            continue
        company = fact.company
        payloads.append(
            {
                "task": task,
                "company": company,
                "source_fact": fact,
                "evidence": fact.evidence_item,
                "signal_type": "revenue_growth_acceleration",
                "category": "growth",
                "title": "收入增速改善",
                "summary": f"{_company_name(company)} {_period_text(fact.period)} 收入增速较对比阶段提高 {round(acceleration * 100, 2)} 个百分点。",
                "severity": "medium",
                "direction": "positive",
                "confidence": _fact_confidence(fact, None),
                "period": fact.period,
                "source_rule": "revenue_growth_acceleration",
                "metadata": {
                    "current_growth": round(current_growth, 6),
                    "previous_growth": round(previous_growth, 6),
                    "acceleration": round(acceleration, 6),
                    "boundary": "研究线索，不构成投资建议",
                },
            }
        )
    return _dedupe_payloads(payloads)


def _facts_for_scope(session: Session, *, company: str | None, period: str | None) -> list[FinancialFact]:
    stmt = (
        select(FinancialFact)
        .options(selectinload(FinancialFact.company), selectinload(FinancialFact.evidence_item))
        .order_by(FinancialFact.company_id, FinancialFact.metric_name, FinancialFact.period)
    )
    if company:
        needle = f"%{company.strip()}%"
        stmt = stmt.join(FinancialFact.company, isouter=True).where(
            or_(Company.name.ilike(needle), Company.symbol.ilike(needle))
        )
    if period:
        stmt = stmt.where(FinancialFact.period == period.strip().upper())
    return list(session.scalars(stmt).unique().all())


def _metric_pairs(
    facts: list[FinancialFact],
    predicate: Callable[[str], bool],
    *,
    period: str | None,
) -> list[tuple[FinancialFact, FinancialFact]]:
    pairs: list[tuple[FinancialFact, FinancialFact]] = []
    grouped: dict[tuple[int | None, str], list[FinancialFact]] = defaultdict(list)
    for fact in facts:
        if predicate(fact.metric_name):
            grouped[(fact.company_id, _metric_key(fact.metric_name))].append(fact)
    for items in grouped.values():
        ordered = sorted(items, key=lambda item: _period_key(item.period))
        for index in range(1, len(ordered)):
            current = ordered[index]
            if period and current.period != period:
                continue
            pairs.append((current, ordered[index - 1]))
    return pairs


def _metric_triples(
    facts: list[FinancialFact],
    predicate: Callable[[str], bool],
    *,
    period: str | None,
) -> list[tuple[FinancialFact, FinancialFact, FinancialFact]]:
    triples: list[tuple[FinancialFact, FinancialFact, FinancialFact]] = []
    grouped: dict[tuple[int | None, str], list[FinancialFact]] = defaultdict(list)
    for fact in facts:
        if predicate(fact.metric_name):
            grouped[(fact.company_id, _metric_key(fact.metric_name))].append(fact)
    for items in grouped.values():
        ordered = sorted(items, key=lambda item: _period_key(item.period))
        for index in range(2, len(ordered)):
            current = ordered[index]
            if period and current.period != period:
                continue
            triples.append((current, ordered[index - 1], ordered[index - 2]))
    return triples


def _group_by_company_period(facts: list[FinancialFact]) -> dict[tuple[int | None, str], list[FinancialFact]]:
    grouped: dict[tuple[int | None, str], list[FinancialFact]] = defaultdict(list)
    for fact in facts:
        grouped[(fact.company_id, fact.period)].append(fact)
    return grouped


def _best_fact(facts: list[FinancialFact], predicate: Callable[[str], bool]) -> FinancialFact | None:
    matches = [fact for fact in facts if predicate(fact.metric_name)]
    if not matches:
        return None
    return sorted(matches, key=lambda fact: (fact.confidence or 0.0, fact.id or 0), reverse=True)[0]


def _has_official_evidence(
    session: Session,
    *,
    company: Company | None,
    company_text: str | None,
    period: str | None,
    task: ReportTask | None,
) -> bool:
    stmt = select(func.count(EvidenceItem.id))
    conditions: list[Any] = []
    if company:
        conditions.append(EvidenceItem.company_id == company.id)
    elif company_text:
        needle = f"%{company_text.strip()}%"
        stmt = stmt.join(EvidenceItem.company, isouter=True)
        conditions.append(or_(Company.name.ilike(needle), Company.symbol.ilike(needle)))
    if task:
        conditions.append(EvidenceItem.metadata_json["task_id"].as_string() == task.task_id)
    if period:
        conditions.append(EvidenceItem.metadata_json["period"].as_string() == period)
    for condition in conditions:
        stmt = stmt.where(condition)
    official_conditions = [
        EvidenceItem.trust_level == "primary",
        EvidenceItem.trust_level == "official",
    ]
    for hint in SOURCE_OFFICIAL_HINTS:
        official_conditions.append(EvidenceItem.source_type.ilike(f"%{hint}%"))
    stmt = stmt.where(or_(*official_conditions))
    return int(session.scalar(stmt) or 0) > 0


def _get_signal(session: Session, signal_ref: int | str) -> InvestmentSignal:
    text = str(signal_ref).strip()
    condition = InvestmentSignal.id == int(text) if text.isdigit() else InvestmentSignal.signal_id == text
    signal = session.scalar(
        select(InvestmentSignal)
        .where(condition)
        .options(
            selectinload(InvestmentSignal.company),
            selectinload(InvestmentSignal.evidence_item),
            selectinload(InvestmentSignal.source_fact).selectinload(FinancialFact.evidence_item),
            selectinload(InvestmentSignal.task),
        )
    )
    if signal is None:
        raise InvestmentSignalNotFound(text)
    return signal


def _get_task_optional(session: Session, task_id: str | None) -> ReportTask | None:
    if not task_id:
        return None
    return _get_task_required(session, task_id)


def _get_task_required(session: Session, task_id: str) -> ReportTask:
    task = session.scalar(select(ReportTask).where(ReportTask.task_id == task_id))
    if task is None:
        raise InvestmentSignalConflict(f"Report task not found: {task_id}")
    return task


def _find_company(session: Session, value: str) -> Company | None:
    needle = value.strip()
    return session.scalar(
        select(Company).where(or_(Company.name.ilike(f"%{needle}%"), Company.symbol.ilike(f"%{needle}%"))).limit(1)
    )


def _scope_company(facts: list[FinancialFact]) -> Company | None:
    for fact in facts:
        if fact.company is not None:
            return fact.company
    return None


def _compact_signal_context(signal: InvestmentSignal) -> dict[str, Any]:
    return {
        "signal_id": signal.signal_id,
        "type": signal.signal_type,
        "title": signal.title,
        "summary": signal.summary,
        "severity": signal.severity,
        "direction": signal.direction,
        "confidence": signal.confidence,
        "period": signal.period,
        "evidence_id": signal.evidence_item.evidence_id if signal.evidence_item else None,
        "boundary": "仅供研究，不构成投资建议",
    }


def _signal_id(
    *,
    signal_type: str,
    company: Company | None,
    period: str | None,
    source_fact: FinancialFact | None,
    evidence: EvidenceItem | None,
    task: ReportTask | None,
    suffix: str | None,
) -> str:
    company_part = str(company.id if company else "scope")
    source_part = str(source_fact.id if source_fact else (evidence.evidence_id if evidence else (task.task_id if task else suffix or "manual")))
    return f"{signal_type}:{company_part}:{period or 'unknown'}:{source_part}"


def _dedupe_payloads(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for payload in payloads:
        key = "|".join(
            [
                str(payload.get("signal_type") or ""),
                str(getattr(payload.get("company"), "id", "") or ""),
                str(payload.get("period") or ""),
                str(getattr(payload.get("source_fact"), "id", "") or payload.get("summary") or ""),
            ]
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(payload)
    return output


def _signal_type(value: Any) -> str:
    text = _optional_string(value)
    if text not in SIGNAL_TYPES:
        raise InvestmentSignalConflict(f"Unsupported signal_type: {value}")
    return text


def _is_margin_metric(value: str) -> bool:
    text = value.lower()
    return "margin" in text or "毛利率" in value or "利润率" in value


def _is_cashflow_metric(value: str) -> bool:
    text = value.lower()
    return "cash flow" in text or "cashflow" in text or "现金流" in value


def _is_profit_metric(value: str) -> bool:
    text = value.lower()
    return "net income" in text or "profit" in text or "净利润" in value or "利润" in value


def _is_revenue_metric(value: str) -> bool:
    text = value.lower()
    return "revenue" in text or "sales" in text or "营业收入" in value or value.strip() == "收入"


def _is_valuation_metric(value: str) -> bool:
    text = value.lower()
    return bool(re.search(r"\b(pe|p/e|pb|ev/ebitda|valuation|market cap)\b", text)) or "估值" in value or "市盈率" in value or "市值" in value


def _metric_key(value: str) -> str:
    text = value.lower()
    for marker in ("revenue", "sales", "营业收入", "收入"):
        if marker in text or marker in value:
            return "revenue"
    for marker in ("gross margin", "margin", "毛利率", "利润率"):
        if marker in text or marker in value:
            return "margin"
    return re.sub(r"\W+", "_", text).strip("_") or value


def _period_key(value: str | None) -> tuple[int, int, str]:
    text = str(value or "").upper()
    year_match = re.search(r"(20\d{2}|19\d{2})", text)
    quarter_match = re.search(r"Q([1-4])", text)
    year = int(year_match.group(1)) if year_match else 0
    quarter = int(quarter_match.group(1)) if quarter_match else 4 if year else 0
    return (year, quarter, text)


def _value_change(current: FinancialFact, previous: FinancialFact) -> float:
    return float(current.value) - float(previous.value)


def _fact_confidence(primary: FinancialFact, secondary: FinancialFact | None) -> float:
    values = [value for value in [primary.confidence, secondary.confidence if secondary else None] if value is not None]
    return round(sum(values) / len(values), 4) if values else 0.72


def _company_name(company: Company | None) -> str:
    if company is None:
        return "目标公司"
    return company.name or company.symbol or "目标公司"


def _period_text(value: str | None) -> str:
    return value or "当前期间"


def _serialize_company(company: Company | None) -> dict[str, Any] | None:
    if company is None:
        return None
    return {"id": company.id, "name": company.name, "symbol": company.symbol, "market": company.market}


def _serialize_evidence(evidence: EvidenceItem | None) -> dict[str, Any] | None:
    if evidence is None:
        return None
    return {
        "id": evidence.id,
        "evidence_id": evidence.evidence_id,
        "title": evidence.title,
        "source_type": evidence.source_type,
        "trust_level": evidence.trust_level,
        "source_url": evidence.source_url,
        "page_no": evidence.page_no,
    }


def _serialize_fact(fact: FinancialFact | None) -> dict[str, Any] | None:
    if fact is None:
        return None
    return {
        "id": fact.id,
        "metric_name": fact.metric_name,
        "metric_type": fact.metric_type,
        "value": fact.value,
        "unit": fact.unit,
        "currency": fact.currency,
        "scale": fact.scale,
        "period": fact.period,
        "confidence": fact.confidence,
        "review_status": fact.review_status,
    }


def _serialize_task(task: ReportTask) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "symbol": task.symbol,
        "period": task.period,
        "status": task.status,
        "metadata": task.metadata_json or {},
    }


def _optional_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value).strip() or None


def _optional_upper(value: Any) -> str | None:
    text = _optional_string(value)
    return text.upper() if text else None


def _optional_float(value: Any, *, default: float | None = None) -> float | None:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _dt(value: Any) -> str | None:
    return value.isoformat() if value else None
