"""Datasource registry and health service for the P1 workbench."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import os
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from src.db.models import DataSource, EvidenceItem, Workspace
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
    "baostock_financials": {"name": "BaoStock 财务指标", "source_type": "financial_statement", "trust_level": "secondary", "market_scope": ["CN"]},
    "tushare_financials": {"name": "Tushare Pro 财务", "source_type": "financial_statement", "trust_level": "secondary", "market_scope": ["CN"]},
    "hkex_announcements": {"name": "港交所公告", "source_type": "official_announcement", "trust_level": "official", "market_scope": ["HK"]},
    "hk_financials": {"name": "港股财务数据", "source_type": "financial_statement", "trust_level": "secondary", "market_scope": ["HK"]},
    "serper": {"name": "Serper 搜索", "source_type": "web_search", "trust_level": "secondary", "market_scope": ["US", "CN", "HK"]},
    "tavily": {"name": "Tavily 搜索", "source_type": "web_search", "trust_level": "secondary", "market_scope": ["US", "CN", "HK"]},
}

EVIDENCE_SOURCE_ALIASES: dict[str, set[str]] = {
    "local_real_data": {"local_real_data"},
    "local_evidence": {"local_evidence", "local_index"},
    "independent_macro": {"independent_macro", "macro_data", "fred", "bls", "bea"},
    "sec_edgar": {"sec_edgar", "sec_companyfacts", "sec_filing", "sec_10k_filing", "sec_10k_section"},
    "yahoo_finance": {"yahoo_finance", "yahoo_profile", "yahoo_financials", "market_api", "market_data"},
    "eastmoney": {"eastmoney", "eastmoney_quote"},
    "sina_finance": {"sina_finance"},
    "cninfo_announcements": {"cninfo", "cninfo_announcement", "cninfo_announcements"},
    "exchange_announcements": {"exchange_announcement", "exchange_announcements"},
    "eastmoney_financials": {"eastmoney_financials"},
    "baostock_financials": {"baostock_financials"},
    "tushare_financials": {"tushare_financials"},
    "hkex_announcements": {"hkex", "hkex_announcement", "hkex_announcements", "hkex_annual_report"},
    "hk_financials": {"hk_financials"},
    "serper": {"serper"},
    "tavily": {"tavily"},
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
            reconciled = 0
            for source_key in source_keys:
                existing = session.scalar(
                    select(DataSource).where(
                        DataSource.workspace_id == (workspace.id if workspace else None),
                        DataSource.source_key == source_key,
                    )
                )
                if existing is not None:
                    credential_status = _credential_status(source_key)
                    should_enable = _credentials_available(credential_status)
                    metadata = dict(existing.metadata_json or {})
                    auto_disabled = metadata.get("auto_disabled_reason") == "missing_credentials"
                    if existing.credential_status != credential_status or (existing.enabled and not should_enable) or (should_enable and auto_disabled):
                        existing.credential_status = credential_status
                        if not should_enable:
                            if existing.enabled:
                                metadata["auto_disabled_reason"] = "missing_credentials"
                            existing.enabled = False
                        elif auto_disabled:
                            existing.enabled = True
                            metadata.pop("auto_disabled_reason", None)
                        existing.metadata_json = metadata
                        reconciled += 1
                    continue
                seed = _catalog_entry(source_key)
                credential_status = _credential_status(source_key)
                item = DataSource(
                    workspace_id=workspace.id if workspace else None,
                    name=seed["name"],
                    source_key=source_key,
                    source_type=seed["source_type"],
                    market_scope=seed["market_scope"],
                    trust_level=seed["trust_level"],
                    config_json={"registered_by": "SearchManager"},
                    enabled=_credentials_available(credential_status),
                    credential_status=credential_status,
                    last_status="not_run",
                    metadata_json={"seeded": True},
                )
                session.add(item)
                created.append(item)
            session.commit()
        return {"created": len(created), "reconciled": reconciled, "source_keys": source_keys}

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
            rows = session.scalars(stmt).unique().all()
            evidence_counts = _evidence_counts_by_source(session, [item.source_key for item in rows])
            items = [self.serialize_source(item, evidence_count=evidence_counts.get(item.source_key, 0)) for item in rows]
        return {"items": items, "total": len(items)}

    def get_source(self, source_ref: int | str) -> dict[str, Any]:
        with self.session_factory() as session:
            item = _get_source(session, source_ref)
            counts = _evidence_counts_by_source(session, [item.source_key])
            return self.serialize_source(item, evidence_count=counts.get(item.source_key, 0))

    def create_source(self, payload: dict[str, Any]) -> dict[str, Any]:
        source_key = str(payload.get("source_key") or "").strip()
        if not source_key:
            raise DataSourceConflict("Datasource source_key is required")
        workspace_ref = payload.get("workspace_id") or payload.get("workspace")
        with self.session_factory() as session:
            workspace = _get_workspace_optional(session, workspace_ref)
            seed = _catalog_entry(source_key)
            credential_status = str(payload.get("credential_status") or _credential_status(source_key))
            requested_enabled = bool(payload.get("enabled", True))
            if requested_enabled and not _credentials_available(credential_status):
                requested_enabled = False
            item = DataSource(
                workspace_id=workspace.id if workspace else None,
                name=str(payload.get("name") or seed["name"]),
                source_key=source_key,
                source_type=str(payload.get("source_type") or seed["source_type"]),
                market_scope=_string_list(payload.get("market_scope")) or seed["market_scope"],
                trust_level=_optional_string(payload.get("trust_level")) or seed["trust_level"],
                config_json=_dict_or_none(payload.get("config")) or {},
                enabled=requested_enabled,
                credential_status=credential_status,
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
            if enabled and not _credentials_available(item.credential_status):
                raise DataSourceConflict(
                    f"Datasource {item.source_key} cannot be enabled until its credentials are configured"
                )
            item.enabled = bool(enabled)
            session.commit()
            return self.serialize_source(item)

    def mark_health(self, source_ref: int | str, payload: dict[str, Any]) -> dict[str, Any]:
        with self.session_factory() as session:
            item = _get_source(session, source_ref)
            requested_status = _optional_string(payload.get("last_status")) or ("success" if not payload.get("last_error") else "failed")
            if requested_status == "success" and payload.get("verified") is not True:
                raise DataSourceConflict("Healthy status must come from a verified datasource probe or sync run")
            item.last_sync_at = _utc_now()
            item.last_status = requested_status
            item.last_error = _optional_string(payload.get("last_error"))
            item.credential_status = _optional_string(payload.get("credential_status")) or item.credential_status
            session.commit()
            return self.serialize_source(item)

    def record_search_run(
        self,
        *,
        search_meta: dict[str, Any],
        task_id: str,
        workspace_id: int | None = None,
    ) -> dict[str, Any]:
        """Persist verified per-engine runtime health from a report search run."""

        engine_meta = search_meta.get("engine_meta") if isinstance(search_meta.get("engine_meta"), dict) else {}
        if not engine_meta:
            return {"updated": 0, "sources": []}
        source_keys = [str(key) for key in engine_meta if str(key)]
        with self.session_factory() as session:
            workspace_condition = (
                or_(DataSource.workspace_id.is_(None), DataSource.workspace_id == workspace_id)
                if workspace_id is not None
                else DataSource.workspace_id.is_(None)
            )
            rows = list(
                session.scalars(
                    select(DataSource).where(
                        DataSource.source_key.in_(source_keys),
                        workspace_condition,
                    )
                ).all()
            )
            updated: list[dict[str, Any]] = []
            for item in rows:
                runtime = engine_meta.get(item.source_key)
                if not isinstance(runtime, dict):
                    continue
                hit_count = _runtime_hit_count(runtime)
                failure_reason = str(runtime.get("failure_reason") or runtime.get("error") or "").strip()
                if hit_count > 0 and failure_reason:
                    status = "partial"
                elif hit_count > 0 or runtime.get("retrieval_available") is True:
                    status = "success"
                else:
                    status = "failed"
                    failure_reason = failure_reason or "no_records_returned"
                metadata = dict(item.metadata_json or {})
                metadata["last_verified_run"] = {
                    "task_id": task_id,
                    "status": status,
                    "hit_count": hit_count,
                    "duration_ms": runtime.get("duration_ms"),
                    "mode": runtime.get("mode") or runtime.get("mode_effective"),
                }
                item.metadata_json = metadata
                item.last_sync_at = _utc_now()
                item.last_status = status
                item.last_error = failure_reason or None
                updated.append({"source_key": item.source_key, "status": status, "hit_count": hit_count})
            session.commit()
        return {"updated": len(updated), "sources": updated}

    def serialize_source(self, item: DataSource, *, evidence_count: int | None = None) -> dict[str, Any]:
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
            "configured": _credentials_available(item.credential_status),
            "operational": bool(item.enabled and _credentials_available(item.credential_status) and item.last_status == "success"),
            "evidence_count": int(evidence_count or 0),
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
    env_name = {"tavily": "TAVILY_API_KEY", "serper": "SERPER_API_KEY", "tushare_financials": "TUSHARE_TOKEN"}.get(source_key)
    if env_name is None:
        return "not_required"
    return "configured" if str(os.getenv(env_name) or "").strip() else "missing"


def _credentials_available(status: str | None) -> bool:
    return str(status or "").strip().lower() in {"not_required", "configured", "valid"}


def _runtime_hit_count(runtime: dict[str, Any]) -> int:
    for key in ("hit_count", "returned_hit_count", "record_count", "result_count"):
        value = runtime.get(key)
        if isinstance(value, (int, float)):
            return max(0, int(value))
    return 0


def _evidence_counts_by_source(session: Session, source_keys: list[str]) -> dict[str, int]:
    raw_counts = {
        str(source_type or "").strip().lower(): int(count or 0)
        for source_type, count in session.execute(
            select(EvidenceItem.source_type, func.count(EvidenceItem.id)).group_by(EvidenceItem.source_type)
        ).all()
        if str(source_type or "").strip()
    }
    return {
        source_key: sum(raw_counts.get(alias, 0) for alias in EVIDENCE_SOURCE_ALIASES.get(source_key, {source_key}))
        for source_key in source_keys
    }


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
