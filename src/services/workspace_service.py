"""Workspace and stock pool configuration service for the P1 workbench."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import re
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from src.db.models import Company, Workspace, WorkspaceCompany


class WorkspaceNotFound(LookupError):
    """Raised when a workspace does not exist."""


class WorkspaceCompanyNotFound(LookupError):
    """Raised when a workspace company cannot be resolved."""


class WorkspaceConflict(RuntimeError):
    """Raised when workspace configuration conflicts with existing data."""


class WorkspaceService:
    """Manage research workspaces and workspace-scoped stock pools."""

    def __init__(self, *, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    def list_workspaces(self, *, market: str | None = None, active_only: bool = False, limit: int = 50) -> dict[str, Any]:
        limit = max(1, min(int(limit or 50), 200))
        with self.session_factory() as session:
            stmt = (
                select(Workspace)
                .options(selectinload(Workspace.companies))
                .order_by(Workspace.created_at.desc(), Workspace.id.desc())
                .limit(limit)
            )
            if market:
                stmt = stmt.where(Workspace.market == market.strip().upper())
            if active_only:
                stmt = stmt.where(Workspace.is_active.is_(True))
            items = [self.serialize_workspace(item, include_companies=False) for item in session.scalars(stmt).unique().all()]
        return {"items": items, "total": len(items)}

    def create_workspace(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise WorkspaceConflict("Workspace name is required")
        slug = _safe_slug(payload.get("slug") or name)
        workspace = Workspace(
            name=name,
            slug=slug,
            market=_optional_upper(payload.get("market")),
            description=_optional_string(payload.get("description")),
            keywords=_string_list(payload.get("keywords")),
            excluded_keywords=_string_list(payload.get("excluded_keywords")),
            focus_metrics=_string_list(payload.get("focus_metrics")),
            risk_types=_string_list(payload.get("risk_types")),
            evidence_threshold=_optional_float(payload.get("evidence_threshold")),
            quality_gate_threshold=_optional_float(payload.get("quality_gate_threshold")),
            default_data_sources=_string_list(payload.get("default_data_sources")),
            report_template=_optional_string(payload.get("report_template")) or "equity_research",
            is_active=bool(payload.get("is_active", True)),
            metadata_json=_dict_or_none(payload.get("metadata")),
        )
        with self.session_factory() as session:
            session.add(workspace)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise WorkspaceConflict(f"Workspace slug already exists: {slug}") from exc
            return self.get_workspace(workspace.id)

    def get_workspace(self, workspace_ref: int | str) -> dict[str, Any]:
        with self.session_factory() as session:
            workspace = self._get_workspace(session, workspace_ref)
            return self.serialize_workspace(workspace, include_companies=True)

    def add_company(self, workspace_ref: int | str, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or payload.get("company_name") or "").strip()
        symbol = str(payload.get("symbol") or "").strip().upper()
        if not name and symbol:
            name = symbol
        if not name or not symbol:
            raise WorkspaceConflict("Company name and symbol are required")
        market = _optional_upper(payload.get("market"))
        aliases = _company_aliases(
            name=name,
            symbol=symbol,
            raw_aliases=payload.get("aliases"),
        )
        with self.session_factory() as session:
            workspace = self._get_workspace(session, workspace_ref)
            existing = session.scalar(
                select(WorkspaceCompany).where(
                    WorkspaceCompany.workspace_id == workspace.id,
                    WorkspaceCompany.symbol == symbol,
                    WorkspaceCompany.market == market,
                )
            )
            if existing is not None:
                raise WorkspaceConflict(f"Company already exists in workspace stock pool: {symbol}")
            company = _get_or_create_company(
                session,
                name=name,
                symbol=symbol,
                market=market,
                industry=_optional_string(payload.get("industry")),
                aliases=aliases,
            )
            item = WorkspaceCompany(
                workspace_id=workspace.id,
                company=company,
                name=name,
                symbol=symbol,
                market=market,
                industry=_optional_string(payload.get("industry")),
                aliases=aliases,
                focus_metrics=_string_list(payload.get("focus_metrics")) or workspace.focus_metrics,
                risk_types=_string_list(payload.get("risk_types")) or workspace.risk_types,
                notes=_optional_string(payload.get("notes")),
                is_active=bool(payload.get("is_active", True)),
                metadata_json=_dict_or_none(payload.get("metadata")),
            )
            session.add(item)
            session.commit()
            return self.serialize_workspace_company(item)

    def list_companies(
        self,
        workspace_ref: int | str,
        *,
        q: str | None = None,
        active_only: bool = False,
        limit: int = 100,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit or 100), 300))
        with self.session_factory() as session:
            workspace = self._get_workspace(session, workspace_ref)
            stmt = (
                select(WorkspaceCompany)
                .where(WorkspaceCompany.workspace_id == workspace.id)
                .order_by(WorkspaceCompany.created_at.desc(), WorkspaceCompany.id.desc())
                .limit(limit)
            )
            stmt = _apply_company_filters(stmt, q=q, active_only=active_only)
            items = [self.serialize_workspace_company(item) for item in session.scalars(stmt).all()]
        return {"items": items, "total": len(items)}

    def resolve_company(self, workspace_ref: int | str, query: str) -> dict[str, Any]:
        needle = str(query or "").strip()
        if not needle:
            raise WorkspaceCompanyNotFound("")
        with self.session_factory() as session:
            workspace = self._get_workspace(session, workspace_ref)
            candidates = session.scalars(
                select(WorkspaceCompany).where(
                    WorkspaceCompany.workspace_id == workspace.id,
                    WorkspaceCompany.is_active.is_(True),
                )
            ).all()
            normalized = _norm(needle)
            for item in candidates:
                values = [item.symbol, item.name, *(item.aliases or [])]
                if normalized in {_norm(value) for value in values if value}:
                    return self.serialize_workspace_company(item)
            like = f"%{needle}%"
            item = session.scalar(
                select(WorkspaceCompany)
                .where(
                    WorkspaceCompany.workspace_id == workspace.id,
                    WorkspaceCompany.is_active.is_(True),
                    or_(
                        WorkspaceCompany.symbol.ilike(like),
                        WorkspaceCompany.name.ilike(like),
                    ),
                )
                .order_by(WorkspaceCompany.id.asc())
            )
            if item is None:
                raise WorkspaceCompanyNotFound(needle)
            return self.serialize_workspace_company(item)

    def serialize_workspace(self, workspace: Workspace, *, include_companies: bool) -> dict[str, Any]:
        companies = [self.serialize_workspace_company(item) for item in workspace.companies]
        active_company_count = sum(1 for item in workspace.companies if item.is_active)
        payload = {
            "id": workspace.id,
            "name": workspace.name,
            "slug": workspace.slug,
            "market": workspace.market,
            "description": workspace.description,
            "keywords": workspace.keywords or [],
            "excluded_keywords": workspace.excluded_keywords or [],
            "focus_metrics": workspace.focus_metrics or [],
            "risk_types": workspace.risk_types or [],
            "evidence_threshold": workspace.evidence_threshold,
            "quality_gate_threshold": workspace.quality_gate_threshold,
            "default_data_sources": workspace.default_data_sources or [],
            "report_template": workspace.report_template,
            "is_active": workspace.is_active,
            "metadata": workspace.metadata_json or {},
            "company_count": len(companies),
            "active_company_count": active_company_count,
            "created_at": _dt(workspace.created_at),
        }
        if include_companies:
            payload["companies"] = companies
        return payload

    def serialize_workspace_company(self, item: WorkspaceCompany) -> dict[str, Any]:
        return {
            "id": item.id,
            "workspace_id": item.workspace_id,
            "company_id": item.company_id,
            "name": item.name,
            "symbol": item.symbol,
            "market": item.market,
            "industry": item.industry,
            "aliases": item.aliases or [],
            "focus_metrics": item.focus_metrics or [],
            "risk_types": item.risk_types or [],
            "notes": item.notes,
            "is_active": item.is_active,
            "metadata": item.metadata_json or {},
            "created_at": _dt(item.created_at),
        }

    def _get_workspace(self, session: Session, workspace_ref: int | str) -> Workspace:
        text = str(workspace_ref).strip()
        condition = Workspace.id == int(text) if text.isdigit() else Workspace.slug == text
        workspace = session.scalar(
            select(Workspace).where(condition).options(selectinload(Workspace.companies))
        )
        if workspace is None:
            raise WorkspaceNotFound(text)
        return workspace


def _apply_company_filters(
    stmt: Select[tuple[WorkspaceCompany]],
    *,
    q: str | None,
    active_only: bool,
) -> Select[tuple[WorkspaceCompany]]:
    if active_only:
        stmt = stmt.where(WorkspaceCompany.is_active.is_(True))
    if q:
        needle = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                WorkspaceCompany.name.ilike(needle),
                WorkspaceCompany.symbol.ilike(needle),
                WorkspaceCompany.industry.ilike(needle),
            )
        )
    return stmt


def _get_or_create_company(
    session: Session,
    *,
    name: str,
    symbol: str,
    market: str | None,
    industry: str | None,
    aliases: list[str],
) -> Company:
    company = session.scalar(select(Company).where(Company.symbol == symbol, Company.market == market))
    if company is not None:
        merged_aliases = _merge_strings(company.aliases or [], aliases)
        company.aliases = merged_aliases
        if industry and not company.industry:
            company.industry = industry
        if name and company.name == symbol:
            company.name = name
        return company
    company = Company(name=name, symbol=symbol, market=market, industry=industry, aliases=aliases)
    session.add(company)
    session.flush()
    return company


def _company_aliases(*, name: str, symbol: str, raw_aliases: Any) -> list[str]:
    return _merge_strings([name, symbol], _string_list(raw_aliases))


def _merge_strings(*groups: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for value in group:
            text = str(value or "").strip()
            key = _norm(text)
            if text and key not in seen:
                result.append(text)
                seen.add(key)
    return result


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        pieces = re.split(r"[,，\n]", value)
    elif isinstance(value, list):
        pieces = value
    else:
        pieces = [value]
    return [str(item).strip() for item in pieces if str(item or "").strip()]


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _optional_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value).strip() or None


def _optional_upper(value: Any) -> str | None:
    text = _optional_string(value)
    return text.upper() if text else None


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_slug(value: Any) -> str:
    text = str(value or "").strip().lower()
    slug = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", text).strip("-")
    return slug or "workspace"


def _norm(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().lower())


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
