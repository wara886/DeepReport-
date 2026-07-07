"""Datasource registry and health service for the P1 workbench."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from src.db.models import DataSource, Workspace
from src.search.search_manager import SearchManager


class DataSourceNotFound(LookupError):
    """Raised when a datasource does not exist."""


class DataSourceConflict(RuntimeError):
    """Raised when datasource configuration conflicts with existing data."""


DEFAULT_SOURCE_CATALOG: dict[str, dict[str, Any]] = {
    "local_real_data": {"name": "本地真实数据", "source_type": "local_dataset", "trust_level": "primary", "market_scope": ["US", "CN", "HK"]},
    "local_evidence": {"name": "本地证据库", "source_type": "local_index", "trust_level": "primary", "market_scope": ["US", "CN", "HK"]},
    "independent_macro": {"name": "宏观独立来源", "source_type": "macro_data", "trust_level": "primary", "market_scope": ["US"]},
    "sec_edgar": {"name": "美国证监会年报", "source_type": "official_filing", "trust_level": "official", "market_scope": ["US"]},
    "yahoo_finance": {"name": "雅虎财经", "source_type": "market_data", "trust_level": "secondary", "market_scope": ["US", "HK"]},
    "eastmoney": {"name": "东方财富行情", "source_type": "market_data", "trust_level": "secondary", "market_scope": ["CN"]},
    "sina_finance": {"name": "新浪财经行情", "source_type": "market_data", "trust_level": "secondary", "market_scope": ["CN", "HK", "US"]},
    "cninfo_announcements": {"name": "巨潮资讯公告", "source_type": "official_announcement", "trust_level": "official", "market_scope": ["CN"]},
    "exchange_announcements": {"name": "交易所公告", "source_type": "official_announcement", "trust_level": "official", "market_scope": ["CN", "HK"]},
    "eastmoney_financials": {"name": "东方财富财务", "source_type": "financial_statement", "trust_level": "secondary", "market_scope": ["CN"]},
    "hkex_announcements": {"name": "港交所公告", "source_type": "official_announcement", "trust_level": "official", "market_scope": ["HK"]},
    "hk_financials": {"name": "港股财务数据", "source_type": "financial_statement", "trust_level": "secondary", "market_scope": ["HK"]},
    "serper": {"name": "Serper 搜索", "source_type": "web_search", "trust_level": "secondary", "market_scope": ["US", "CN", "HK"]},
    "tavily": {"name": "Tavily 搜索", "source_type": "web_search", "trust_level": "secondary", "market_scope": ["US", "CN", "HK"]},
}


class DataSourceService:
    """Manage datasource registry entries and lightweight health state."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        search_manager_factory: Callable[[], SearchManager] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.search_manager_factory = search_manager_factory or SearchManager.with_local_sources

    def seed_registered_sources(self, *, workspace_ref: int | str | None = None) -> dict[str, Any]:
        source_keys = self.search_manager_factory().engine_names()
        with self.session_factory() as session:
            workspace = _get_workspace_optional(session, workspace_ref)
            created: list[DataSource] = []
            for source_key in source_keys:
                existing = session.scalar(
                    select(DataSource).where(
                        DataSource.workspace_id == (workspace.id if workspace else None),
                        DataSource.source_key == source_key,
                    )
                )
                if existing is not None:
                    continue
                seed = _catalog_entry(source_key)
                item = DataSource(
                    workspace_id=workspace.id if workspace else None,
                    name=seed["name"],
                    source_key=source_key,
                    source_type=seed["source_type"],
                    market_scope=seed["market_scope"],
                    trust_level=seed["trust_level"],
                    config_json={"registered_by": "SearchManager"},
                    enabled=True,
                    credential_status=_credential_status(source_key),
                    last_status="not_run",
                    metadata_json={"seeded": True},
                )
                session.add(item)
                created.append(item)
            session.commit()
        return {"created": len(created), "source_keys": source_keys}

    def list_sources(
        self,
        *,
        workspace_ref: int | str | None = None,
        enabled: bool | None = None,
        q: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit or 100), 300))
        with self.session_factory() as session:
            workspace = _get_workspace_optional(session, workspace_ref)
            stmt = (
                select(DataSource)
                .options(selectinload(DataSource.workspace))
                .order_by(DataSource.workspace_id.asc().nullsfirst(), DataSource.source_key.asc())
                .limit(limit)
            )
            if workspace_ref is not None:
                stmt = stmt.where(DataSource.workspace_id == (workspace.id if workspace else None))
            if enabled is not None:
                stmt = stmt.where(DataSource.enabled.is_(enabled))
            stmt = _apply_search(stmt, q=q)
            items = [self.serialize_source(item) for item in session.scalars(stmt).unique().all()]
        return {"items": items, "total": len(items)}

    def get_source(self, source_ref: int | str) -> dict[str, Any]:
        with self.session_factory() as session:
            return self.serialize_source(_get_source(session, source_ref))

    def create_source(self, payload: dict[str, Any]) -> dict[str, Any]:
        source_key = str(payload.get("source_key") or "").strip()
        if not source_key:
            raise DataSourceConflict("Datasource source_key is required")
        workspace_ref = payload.get("workspace_id") or payload.get("workspace")
        with self.session_factory() as session:
            workspace = _get_workspace_optional(session, workspace_ref)
            seed = _catalog_entry(source_key)
            item = DataSource(
                workspace_id=workspace.id if workspace else None,
                name=str(payload.get("name") or seed["name"]),
                source_key=source_key,
                source_type=str(payload.get("source_type") or seed["source_type"]),
                market_scope=_string_list(payload.get("market_scope")) or seed["market_scope"],
                trust_level=_optional_string(payload.get("trust_level")) or seed["trust_level"],
                config_json=_dict_or_none(payload.get("config")) or {},
                enabled=bool(payload.get("enabled", True)),
                credential_status=str(payload.get("credential_status") or _credential_status(source_key)),
                last_status=_optional_string(payload.get("last_status")) or "not_run",
                last_error=_optional_string(payload.get("last_error")),
                metadata_json=_dict_or_none(payload.get("metadata")),
            )
            session.add(item)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise DataSourceConflict(f"Datasource already exists: {source_key}") from exc
            return self.serialize_source(item)

    def set_enabled(self, source_ref: int | str, enabled: bool) -> dict[str, Any]:
        with self.session_factory() as session:
            item = _get_source(session, source_ref)
            item.enabled = bool(enabled)
            session.commit()
            return self.serialize_source(item)

    def mark_health(self, source_ref: int | str, payload: dict[str, Any]) -> dict[str, Any]:
        with self.session_factory() as session:
            item = _get_source(session, source_ref)
            item.last_sync_at = _utc_now()
            item.last_status = _optional_string(payload.get("last_status")) or ("success" if not payload.get("last_error") else "failed")
            item.last_error = _optional_string(payload.get("last_error"))
            item.credential_status = _optional_string(payload.get("credential_status")) or item.credential_status
            session.commit()
            return self.serialize_source(item)

    def serialize_source(self, item: DataSource) -> dict[str, Any]:
        return {
            "id": item.id,
            "workspace_id": item.workspace_id,
            "workspace_name": item.workspace.name if item.workspace else None,
            "name": item.name,
            "source_key": item.source_key,
            "source_type": item.source_type,
            "market_scope": item.market_scope or [],
            "trust_level": item.trust_level,
            "config": item.config_json or {},
            "enabled": item.enabled,
            "credential_status": item.credential_status,
            "last_sync_at": _dt(item.last_sync_at),
            "last_status": item.last_status,
            "last_error": item.last_error,
            "metadata": item.metadata_json or {},
            "created_at": _dt(item.created_at),
        }


def _catalog_entry(source_key: str) -> dict[str, Any]:
    default = {"name": source_key, "source_type": "external", "trust_level": "secondary", "market_scope": []}
    return {**default, **DEFAULT_SOURCE_CATALOG.get(source_key, {})}


def _credential_status(source_key: str) -> str:
    return "required" if source_key in {"tavily", "serper"} else "not_required"


def _get_workspace_optional(session: Session, workspace_ref: int | str | None) -> Workspace | None:
    if workspace_ref in (None, ""):
        return None
    text = str(workspace_ref).strip()
    condition = Workspace.id == int(text) if text.isdigit() else Workspace.slug == text
    workspace = session.scalar(select(Workspace).where(condition))
    if workspace is None:
        raise DataSourceNotFound(f"Workspace not found: {workspace_ref}")
    return workspace


def _get_source(session: Session, source_ref: int | str) -> DataSource:
    text = str(source_ref).strip()
    condition = DataSource.id == int(text) if text.isdigit() else DataSource.source_key == text
    source = session.scalar(select(DataSource).where(condition).options(selectinload(DataSource.workspace)))
    if source is None:
        raise DataSourceNotFound(text)
    return source


def _apply_search(stmt: Select[tuple[DataSource]], *, q: str | None) -> Select[tuple[DataSource]]:
    if q:
        needle = f"%{q.strip()}%"
        stmt = stmt.where(or_(DataSource.name.ilike(needle), DataSource.source_key.ilike(needle), DataSource.source_type.ilike(needle)))
    return stmt


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _optional_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value).strip()


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
