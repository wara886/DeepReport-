"""Financial fact center service for metric storage and source binding."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from src.db.models import Company, EvidenceItem, FinancialFact


class FinancialFactNotFound(LookupError):
    """Raised when a financial fact does not exist."""


class FinancialFactConflict(RuntimeError):
    """Raised when a financial fact payload is invalid."""


MONEY_METRIC_HINTS = ("revenue", "income", "profit", "cash", "assets", "liabilities", "equity", "营业收入", "收入", "利润", "现金", "资产", "负债")


class FinancialFactService:
    def __init__(self, *, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    def import_fact(self, payload: dict[str, Any]) -> dict[str, Any]:
        metric_name = _optional_string(payload.get("metric_name") or payload.get("metric"))
        period = _optional_string(payload.get("period"))
        if not metric_name or not period:
            raise FinancialFactConflict("metric_name and period are required")
        value = _float_required(payload.get("value"))
        metric_type = _optional_string(payload.get("metric_type")) or _infer_metric_type(metric_name, payload)
        currency = _optional_upper(payload.get("currency"))
        unit = _optional_string(payload.get("unit"))
        scale = _optional_string(payload.get("scale"))
        if metric_type == "money" and (not currency or not unit):
            raise FinancialFactConflict("Money facts require currency and unit")
        with self.session_factory() as session:
            company = _get_or_create_company(
                session,
                name=_optional_string(payload.get("company_name")),
                symbol=_optional_string(payload.get("symbol")),
                market=_optional_string(payload.get("market")),
            )
            evidence = _get_evidence_optional(session, payload.get("evidence_id") or payload.get("evidence_item_id"))
            fact = FinancialFact(
                company_id=company.id if company else None,
                evidence_item_id=evidence.id if evidence else None,
                metric_name=metric_name,
                metric_type=metric_type,
                value=value,
                unit=unit,
                currency=currency,
                scale=scale,
                period=period,
                fiscal_year=_optional_int(payload.get("fiscal_year")),
                source_url=_optional_string(payload.get("source_url")) or (evidence.source_url if evidence else None),
                confidence=_optional_float(payload.get("confidence")),
                review_status=_optional_string(payload.get("review_status")) or "pending",
                metadata_json=_dict_or_none(payload.get("metadata")) or {},
            )
            session.add(fact)
            session.commit()
            return self.serialize_fact(fact)

    def list_facts(
        self,
        *,
        company: str | None = None,
        metric: str | None = None,
        period: str | None = None,
        review_status: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit or 100), 300))
        with self.session_factory() as session:
            stmt = (
                select(FinancialFact)
                .options(selectinload(FinancialFact.company), selectinload(FinancialFact.evidence_item))
                .order_by(FinancialFact.created_at.desc(), FinancialFact.id.desc())
                .limit(limit)
            )
            if company:
                needle = f"%{company.strip()}%"
                stmt = stmt.join(FinancialFact.company, isouter=True).where(or_(Company.name.ilike(needle), Company.symbol.ilike(needle)))
            if metric:
                stmt = stmt.where(FinancialFact.metric_name.ilike(f"%{metric.strip()}%"))
            if period:
                stmt = stmt.where(FinancialFact.period == period.strip().upper())
            if review_status:
                stmt = stmt.where(FinancialFact.review_status == review_status)
            items = [self.serialize_fact(item) for item in session.scalars(stmt).unique().all()]
        return {"items": items, "total": len(items)}

    def get_fact(self, fact_id: int) -> dict[str, Any]:
        with self.session_factory() as session:
            fact = session.scalar(
                select(FinancialFact)
                .where(FinancialFact.id == fact_id)
                .options(selectinload(FinancialFact.company), selectinload(FinancialFact.evidence_item))
            )
            if fact is None:
                raise FinancialFactNotFound(fact_id)
            return self.serialize_fact(fact)

    def serialize_fact(self, fact: FinancialFact) -> dict[str, Any]:
        return {
            "id": fact.id,
            "company_id": fact.company_id,
            "company": _serialize_company(fact.company),
            "evidence_item_id": fact.evidence_item_id,
            "evidence": _serialize_evidence(fact.evidence_item),
            "metric_name": fact.metric_name,
            "metric_type": fact.metric_type,
            "value": fact.value,
            "unit": fact.unit,
            "currency": fact.currency,
            "scale": fact.scale,
            "period": fact.period,
            "fiscal_year": fact.fiscal_year,
            "source_url": fact.source_url,
            "confidence": fact.confidence,
            "review_status": fact.review_status,
            "metadata": fact.metadata_json or {},
            "created_at": fact.created_at.isoformat() if fact.created_at else None,
        }


def _get_or_create_company(session: Session, *, name: str | None, symbol: str | None, market: str | None) -> Company | None:
    normalized_symbol = symbol.upper() if symbol else None
    normalized_market = market.upper() if market else None
    if not (name or normalized_symbol):
        return None
    if normalized_symbol:
        company = session.scalar(select(Company).where(Company.symbol == normalized_symbol, Company.market == normalized_market))
        if company is not None:
            if name and company.name == normalized_symbol:
                company.name = name
            return company
    if name:
        company = session.scalar(select(Company).where(Company.name == name, Company.market == normalized_market))
        if company is not None:
            return company
    company = Company(name=name or normalized_symbol or "未知公司", symbol=normalized_symbol, market=normalized_market, aliases=[item for item in [name, normalized_symbol] if item])
    session.add(company)
    session.flush()
    return company


def _get_evidence_optional(session: Session, ref: Any) -> EvidenceItem | None:
    if ref in (None, ""):
        return None
    text = str(ref).strip()
    condition = EvidenceItem.id == int(text) if text.isdigit() else EvidenceItem.evidence_id == text
    evidence = session.scalar(select(EvidenceItem).where(condition))
    if evidence is None:
        raise FinancialFactConflict(f"Evidence not found: {ref}")
    return evidence


def _infer_metric_type(metric_name: str, payload: dict[str, Any]) -> str:
    explicit_currency = _optional_string(payload.get("currency"))
    lower = metric_name.lower()
    if explicit_currency or any(hint.lower() in lower for hint in MONEY_METRIC_HINTS):
        return "money"
    if "margin" in lower or "率" in metric_name:
        return "ratio"
    return "number"


def _float_required(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise FinancialFactConflict("value must be numeric") from exc


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise FinancialFactConflict("confidence must be numeric") from exc


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise FinancialFactConflict("fiscal_year must be integer") from exc


def _optional_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value).strip() or None


def _optional_upper(value: Any) -> str | None:
    text = _optional_string(value)
    return text.upper() if text else None


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


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
        "source_url": evidence.source_url,
        "page_no": evidence.page_no,
    }
