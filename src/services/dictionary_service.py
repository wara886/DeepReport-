"""Financial dictionary and alias resolution service for the P1 workbench."""

from __future__ import annotations

from collections.abc import Callable
import re
from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from src.db.models import DictionaryAlias, DictionaryTerm, Workspace


class DictionaryTermNotFound(LookupError):
    """Raised when a dictionary term cannot be found."""


class DictionaryConflict(RuntimeError):
    """Raised when dictionary input is invalid or conflicts with existing data."""


TERM_TYPES = {"company", "product", "metric", "industry", "risk", "exclude"}


class DictionaryService:
    """Manage canonical financial terms and resolve aliases."""

    def __init__(self, *, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    def create_term(self, payload: dict[str, Any]) -> dict[str, Any]:
        term_type = _term_type(payload.get("term_type") or payload.get("type"))
        canonical_name = _optional_string(payload.get("canonical_name") or payload.get("name"))
        if not canonical_name:
            raise DictionaryConflict("canonical_name is required")
        aliases = _merge_strings([canonical_name], _string_list(payload.get("aliases")))
        market = _optional_upper(payload.get("market"))
        with self.session_factory() as session:
            workspace = _get_workspace_optional(session, payload.get("workspace_id") or payload.get("workspace"))
            term = DictionaryTerm(
                workspace_id=workspace.id if workspace else None,
                term_type=term_type,
                canonical_name=canonical_name,
                normalized_key=_norm(canonical_name),
                market=market,
                symbol=_optional_upper(payload.get("symbol")),
                description=_optional_string(payload.get("description")),
                metadata_json=_dict_or_none(payload.get("metadata")) or {},
                is_active=bool(payload.get("is_active", True)),
            )
            term.aliases = [
                DictionaryAlias(
                    term_type=term_type,
                    alias=alias,
                    normalized_key=_norm(alias),
                    source=_optional_string(payload.get("source")) or "manual",
                )
                for alias in aliases
            ]
            session.add(term)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise DictionaryConflict(f"Dictionary term already exists: {term_type}/{canonical_name}") from exc
            return self.serialize_term(term)

    def list_terms(
        self,
        *,
        term_type: str | None = None,
        q: str | None = None,
        workspace_ref: int | str | None = None,
        active_only: bool = False,
        limit: int = 100,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit or 100), 300))
        with self.session_factory() as session:
            workspace = _get_workspace_optional(session, workspace_ref)
            stmt = (
                select(DictionaryTerm)
                .options(selectinload(DictionaryTerm.aliases), selectinload(DictionaryTerm.workspace))
                .order_by(DictionaryTerm.created_at.desc(), DictionaryTerm.id.desc())
                .limit(limit)
            )
            if term_type:
                stmt = stmt.where(DictionaryTerm.term_type == _term_type(term_type))
            if workspace_ref is not None:
                stmt = stmt.where(DictionaryTerm.workspace_id == (workspace.id if workspace else None))
            if active_only:
                stmt = stmt.where(DictionaryTerm.is_active.is_(True))
            stmt = _apply_search(stmt, q=q)
            items = [self.serialize_term(item) for item in session.scalars(stmt).unique().all()]
        return {"items": items, "total": len(items)}

    def get_term(self, term_ref: int | str) -> dict[str, Any]:
        with self.session_factory() as session:
            return self.serialize_term(_get_term(session, term_ref))

    def resolve_alias(
        self,
        *,
        query: str,
        term_type: str | None = None,
        workspace_ref: int | str | None = None,
        market: str | None = None,
    ) -> dict[str, Any]:
        normalized = _norm(query)
        if not normalized:
            raise DictionaryTermNotFound("")
        with self.session_factory() as session:
            workspace = _get_workspace_optional(session, workspace_ref)
            stmt = (
                select(DictionaryAlias)
                .join(DictionaryAlias.term)
                .options(selectinload(DictionaryAlias.term).selectinload(DictionaryTerm.aliases))
                .where(DictionaryAlias.normalized_key == normalized, DictionaryTerm.is_active.is_(True))
            )
            if term_type:
                stmt = stmt.where(DictionaryAlias.term_type == _term_type(term_type))
            if workspace_ref is not None:
                stmt = stmt.where(DictionaryTerm.workspace_id == (workspace.id if workspace else None))
            if market:
                upper_market = _optional_upper(market)
                stmt = stmt.where(or_(DictionaryTerm.market == upper_market, DictionaryTerm.market.is_(None)))
            alias = session.scalar(stmt.order_by(DictionaryTerm.workspace_id.desc().nullslast(), DictionaryTerm.id.asc()))
            if alias is None:
                raise DictionaryTermNotFound(query)
            payload = self.serialize_term(alias.term)
            payload["matched_alias"] = alias.alias
            payload["normalized_query"] = normalized
            return payload

    def resolve_company(self, query: str, *, workspace_ref: int | str | None = None, market: str | None = None) -> dict[str, Any]:
        return self.resolve_alias(query=query, term_type="company", workspace_ref=workspace_ref, market=market)

    def resolve_metric(self, query: str, *, workspace_ref: int | str | None = None) -> dict[str, Any]:
        return self.resolve_alias(query=query, term_type="metric", workspace_ref=workspace_ref)

    def serialize_term(self, item: DictionaryTerm) -> dict[str, Any]:
        return {
            "id": item.id,
            "workspace_id": item.workspace_id,
            "workspace_name": item.workspace.name if item.workspace else None,
            "term_type": item.term_type,
            "canonical_name": item.canonical_name,
            "normalized_key": item.normalized_key,
            "market": item.market,
            "symbol": item.symbol,
            "description": item.description,
            "aliases": [alias.alias for alias in item.aliases],
            "metadata": item.metadata_json or {},
            "is_active": item.is_active,
            "created_at": _dt(item.created_at),
        }


def _get_term(session: Session, term_ref: int | str) -> DictionaryTerm:
    text = str(term_ref).strip()
    condition = DictionaryTerm.id == int(text) if text.isdigit() else DictionaryTerm.normalized_key == _norm(text)
    term = session.scalar(
        select(DictionaryTerm)
        .where(condition)
        .options(selectinload(DictionaryTerm.aliases), selectinload(DictionaryTerm.workspace))
    )
    if term is None:
        raise DictionaryTermNotFound(text)
    return term


def _get_workspace_optional(session: Session, workspace_ref: int | str | None) -> Workspace | None:
    if workspace_ref in (None, ""):
        return None
    text = str(workspace_ref).strip()
    condition = Workspace.id == int(text) if text.isdigit() else Workspace.slug == text
    workspace = session.scalar(select(Workspace).where(condition))
    if workspace is None:
        raise DictionaryConflict(f"Workspace not found: {workspace_ref}")
    return workspace


def _apply_search(stmt: Select[tuple[DictionaryTerm]], *, q: str | None) -> Select[tuple[DictionaryTerm]]:
    if not q:
        return stmt
    needle = f"%{q.strip()}%"
    return stmt.where(
        or_(
            DictionaryTerm.canonical_name.ilike(needle),
            DictionaryTerm.symbol.ilike(needle),
            DictionaryTerm.description.ilike(needle),
            DictionaryTerm.aliases.any(DictionaryAlias.alias.ilike(needle)),
        )
    )


def _term_type(value: Any) -> str:
    text = str(value or "").strip().lower()
    aliases = {
        "company_alias": "company",
        "metric_alias": "metric",
        "risk_word": "risk",
        "exclude_word": "exclude",
    }
    text = aliases.get(text, text)
    if text not in TERM_TYPES:
        raise DictionaryConflict(f"Unsupported dictionary term_type: {value}")
    return text


def _norm(value: Any) -> str:
    return re.sub(r"[\s\-_./()（）]+", "", str(value or "").strip().lower())


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


def _optional_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value).strip() or None


def _optional_upper(value: Any) -> str | None:
    text = _optional_string(value)
    return text.upper() if text else None


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _dt(value: Any) -> str | None:
    return value.isoformat() if value is not None else None
