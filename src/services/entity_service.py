"""Entity and relation store for the P2 workbench graph layer."""

from __future__ import annotations

from collections.abc import Callable
import re
from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from src.db.models import Document, Entity, EntityRelation, EvidenceItem, Workspace


class EntityNotFound(LookupError):
    """Raised when an entity cannot be found."""


class EntityConflict(RuntimeError):
    """Raised when entity or relation input is invalid."""


ENTITY_TYPES = {
    "company",
    "ticker",
    "industry",
    "product",
    "customer",
    "supplier",
    "executive",
    "metric",
    "document",
    "risk_event",
    "news_event",
    "peer_company",
}
RELATION_TYPES = {
    "BELONGS_TO",
    "PUBLISHED",
    "HAS_PRODUCT",
    "HAS_METRIC",
    "HAS_EVENT",
    "PEER_OF",
    "SUPPLIES_TO",
    "MENTIONED_IN",
}
METRIC_PATTERNS = [
    ("revenue", "营业收入", re.compile(r"\b(revenue|sales)\b|营业收入|收入", re.I)),
    ("gross_margin", "毛利率", re.compile(r"\b(gross margin|gross profit margin)\b|毛利率|毛利", re.I)),
    ("net_income", "净利润", re.compile(r"\b(net income|net profit)\b|净利润|归母净利润", re.I)),
    ("free_cash_flow", "自由现金流", re.compile(r"\bfree cash flow\b|自由现金流", re.I)),
    ("operating_cash_flow", "经营现金流", re.compile(r"\boperating cash flow\b|经营现金流", re.I)),
    ("valuation", "估值", re.compile(r"\b(valuation|pe ratio|p/e)\b|估值|市盈率", re.I)),
]
RISK_PATTERNS = [
    ("supply_chain_risk", "供应链风险", re.compile(r"\b(supply chain|supplier)\b|供应链|供应商", re.I)),
    ("margin_pressure", "利润率压力", re.compile(r"\b(margin pressure|margin decline)\b|利润率压力|毛利率下滑", re.I)),
    ("demand_risk", "需求风险", re.compile(r"\b(demand risk|weak demand)\b|需求风险|需求疲软", re.I)),
    ("regulatory_risk", "监管风险", re.compile(r"\b(regulatory|regulation)\b|监管风险|政策风险", re.I)),
]


class EntityService:
    """Manage normalized entities, relations, and evidence-backed graph records."""

    def __init__(self, *, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    def upsert_entity(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.session_factory() as session:
            entity = _upsert_entity(session, payload)
            session.commit()
            return self.serialize_entity(entity)

    def get_entity(self, entity_ref: int | str) -> dict[str, Any]:
        with self.session_factory() as session:
            entity = _get_entity(session, entity_ref)
            return self.serialize_entity(entity)

    def list_entities(
        self,
        *,
        entity_type: str | None = None,
        q: str | None = None,
        market: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit or 100), 300))
        with self.session_factory() as session:
            stmt = (
                select(Entity)
                .options(selectinload(Entity.source_evidence_item))
                .order_by(Entity.updated_at.desc(), Entity.id.desc())
                .limit(limit)
            )
            if entity_type:
                stmt = stmt.where(Entity.entity_type == _entity_type(entity_type))
            if market:
                stmt = stmt.where(Entity.market == _optional_upper(market))
            stmt = _apply_entity_search(stmt, q=q)
            items = [self.serialize_entity(entity) for entity in session.scalars(stmt).unique().all()]
        return {"items": items, "total": len(items)}

    def upsert_relation(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.session_factory() as session:
            relation = _upsert_relation(session, payload)
            session.commit()
            return self.serialize_relation(relation)

    def list_relations(
        self,
        *,
        relation_type: str | None = None,
        entity_id: int | None = None,
        q: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit or 100), 300))
        with self.session_factory() as session:
            stmt = (
                select(EntityRelation)
                .options(
                    selectinload(EntityRelation.source_entity),
                    selectinload(EntityRelation.target_entity),
                    selectinload(EntityRelation.source_evidence_item),
                )
                .order_by(EntityRelation.updated_at.desc(), EntityRelation.id.desc())
                .limit(limit)
            )
            if relation_type:
                stmt = stmt.where(EntityRelation.relation_type == _relation_type(relation_type))
            if entity_id:
                stmt = stmt.where(
                    or_(
                        EntityRelation.source_entity_id == entity_id,
                        EntityRelation.target_entity_id == entity_id,
                    )
                )
            stmt = _apply_relation_search(stmt, q=q)
            items = [self.serialize_relation(relation) for relation in session.scalars(stmt).unique().all()]
        return {"items": items, "total": len(items)}

    def extract_from_evidence(self, evidence_ref: int | str) -> dict[str, Any]:
        with self.session_factory() as session:
            evidence = _get_evidence(session, evidence_ref)
            entity_payloads, relation_payloads = _entity_payloads_from_evidence(evidence)
            entities = [_upsert_entity(session, payload) for payload in entity_payloads]
            entity_by_key = {entity.entity_key: entity for entity in entities}
            relation_payloads = [
                _resolve_relation_payload(payload, entity_by_key)
                for payload in relation_payloads
                if payload.get("source_entity_key") in entity_by_key and payload.get("target_entity_key") in entity_by_key
            ]
            relations = [_upsert_relation(session, payload) for payload in relation_payloads]
            session.commit()
            return {
                "evidence_id": evidence.evidence_id,
                "entities": [self.serialize_entity(entity) for entity in entities],
                "relations": [self.serialize_relation(relation) for relation in relations],
                "entity_count": len(entities),
                "relation_count": len(relations),
            }

    def graph_summary(self, *, limit: int = 100) -> dict[str, Any]:
        limit = max(1, min(int(limit or 100), 300))
        with self.session_factory() as session:
            entities = session.scalars(
                select(Entity)
                .options(selectinload(Entity.source_evidence_item))
                .order_by(Entity.updated_at.desc(), Entity.id.desc())
                .limit(limit)
            ).all()
            relations = session.scalars(
                select(EntityRelation)
                .options(
                    selectinload(EntityRelation.source_entity).selectinload(Entity.source_evidence_item),
                    selectinload(EntityRelation.target_entity).selectinload(Entity.source_evidence_item),
                    selectinload(EntityRelation.source_evidence_item),
                )
                .order_by(EntityRelation.updated_at.desc(), EntityRelation.id.desc())
                .limit(limit)
            ).all()
        return {
            "nodes": [self.serialize_entity(entity) for entity in entities],
            "edges": [self.serialize_relation(relation) for relation in relations],
            "node_count": len(entities),
            "edge_count": len(relations),
        }

    def serialize_entity(self, entity: Entity) -> dict[str, Any]:
        return {
            "id": entity.id,
            "workspace_id": entity.workspace_id,
            "entity_key": entity.entity_key,
            "entity_type": entity.entity_type,
            "canonical_name": entity.canonical_name,
            "normalized_key": entity.normalized_key,
            "market": entity.market,
            "symbol": entity.symbol,
            "description": entity.description,
            "confidence": entity.confidence,
            "source_evidence_id": entity.source_evidence_item.evidence_id if entity.source_evidence_item else None,
            "metadata": entity.metadata_json or {},
            "created_at": _dt(entity.created_at),
            "updated_at": _dt(entity.updated_at),
        }

    def serialize_relation(self, relation: EntityRelation) -> dict[str, Any]:
        return {
            "id": relation.id,
            "relation_key": relation.relation_key,
            "relation_type": relation.relation_type,
            "source_entity_id": relation.source_entity_id,
            "target_entity_id": relation.target_entity_id,
            "source": self.serialize_entity(relation.source_entity),
            "target": self.serialize_entity(relation.target_entity),
            "confidence": relation.confidence,
            "source_evidence_id": relation.source_evidence_item.evidence_id if relation.source_evidence_item else None,
            "metadata": relation.metadata_json or {},
            "created_at": _dt(relation.created_at),
            "updated_at": _dt(relation.updated_at),
        }


def _upsert_entity(session: Session, payload: dict[str, Any]) -> Entity:
    entity_type = _entity_type(payload.get("entity_type") or payload.get("type"))
    canonical_name = _optional_string(payload.get("canonical_name") or payload.get("name"))
    if not canonical_name:
        raise EntityConflict("canonical_name is required")
    workspace = _get_workspace_optional(session, payload.get("workspace_id") or payload.get("workspace"))
    market = _optional_upper(payload.get("market"))
    symbol = _optional_upper(payload.get("symbol"))
    entity_key = _optional_string(payload.get("entity_key")) or _entity_key(
        entity_type=entity_type,
        canonical_name=canonical_name,
        market=market,
        symbol=symbol,
        workspace_id=workspace.id if workspace else None,
    )
    source_evidence = _get_evidence_optional(session, payload.get("source_evidence_id") or payload.get("evidence_id"))
    entity = session.scalar(select(Entity).where(Entity.entity_key == entity_key))
    if entity is None:
        entity = Entity(
            workspace_id=workspace.id if workspace else None,
            entity_key=entity_key,
            entity_type=entity_type,
            canonical_name=canonical_name,
            normalized_key=_norm(canonical_name),
            market=market,
            symbol=symbol,
            description=_optional_string(payload.get("description")),
            confidence=_optional_float(payload.get("confidence"), default=0.8),
            source_evidence_item_id=source_evidence.id if source_evidence else None,
            metadata_json=_dict_or_empty(payload.get("metadata")),
        )
        session.add(entity)
    else:
        entity.canonical_name = canonical_name
        entity.normalized_key = _norm(canonical_name)
        entity.market = market or entity.market
        entity.symbol = symbol or entity.symbol
        entity.description = _optional_string(payload.get("description")) or entity.description
        entity.confidence = max(float(entity.confidence or 0.0), _optional_float(payload.get("confidence"), default=0.8))
        if source_evidence:
            entity.source_evidence_item_id = source_evidence.id
        entity.metadata_json = _merge_dicts(entity.metadata_json or {}, _dict_or_empty(payload.get("metadata")))
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise EntityConflict(f"Entity upsert conflict: {entity_key}") from exc
    return entity


def _upsert_relation(session: Session, payload: dict[str, Any]) -> EntityRelation:
    source = _resolve_entity(session, payload.get("source_entity_id") or payload.get("source"))
    target = _resolve_entity(session, payload.get("target_entity_id") or payload.get("target"))
    relation_type = _relation_type(payload.get("relation_type") or payload.get("type"))
    source_evidence = _get_evidence_optional(session, payload.get("source_evidence_id") or payload.get("evidence_id"))
    relation_key = _optional_string(payload.get("relation_key")) or _relation_key(
        source.id,
        relation_type,
        target.id,
        source_evidence.evidence_id if source_evidence else None,
    )
    relation = session.scalar(select(EntityRelation).where(EntityRelation.relation_key == relation_key))
    if relation is None:
        relation = EntityRelation(
            relation_key=relation_key,
            source_entity_id=source.id,
            target_entity_id=target.id,
            relation_type=relation_type,
            confidence=_optional_float(payload.get("confidence"), default=0.75),
            source_evidence_item_id=source_evidence.id if source_evidence else None,
            metadata_json=_dict_or_empty(payload.get("metadata")),
        )
        session.add(relation)
    else:
        relation.confidence = max(float(relation.confidence or 0.0), _optional_float(payload.get("confidence"), default=0.75))
        if source_evidence:
            relation.source_evidence_item_id = source_evidence.id
        relation.metadata_json = _merge_dicts(relation.metadata_json or {}, _dict_or_empty(payload.get("metadata")))
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise EntityConflict(f"Relation upsert conflict: {relation_key}") from exc
    return relation


def _resolve_entity(session: Session, ref: Any) -> Entity:
    if isinstance(ref, dict):
        return _upsert_entity(session, ref)
    if ref in (None, ""):
        raise EntityConflict("source and target entities are required")
    return _get_entity(session, ref)


def _get_entity(session: Session, entity_ref: int | str) -> Entity:
    text = str(entity_ref).strip()
    condition = Entity.id == int(text) if text.isdigit() else Entity.entity_key == text
    entity = session.scalar(select(Entity).where(condition).options(selectinload(Entity.source_evidence_item)))
    if entity is None:
        raise EntityNotFound(text)
    return entity


def _get_evidence(session: Session, evidence_ref: int | str) -> EvidenceItem:
    evidence = _get_evidence_optional(session, evidence_ref)
    if evidence is None:
        raise EntityConflict(f"Evidence not found: {evidence_ref}")
    return evidence


def _get_evidence_optional(session: Session, evidence_ref: Any) -> EvidenceItem | None:
    if evidence_ref in (None, ""):
        return None
    text = str(evidence_ref).strip()
    condition = EvidenceItem.id == int(text) if text.isdigit() else EvidenceItem.evidence_id == text
    return session.scalar(
        select(EvidenceItem)
        .where(condition)
        .options(selectinload(EvidenceItem.company), selectinload(EvidenceItem.document))
    )


def _entity_payloads_from_evidence(evidence: EvidenceItem) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    text = f"{evidence.title or ''}\n{evidence.content or ''}"
    entities: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    evidence_id = evidence.evidence_id
    company_key = ""
    document_key = ""
    if evidence.company:
        company_key = _entity_key(
            entity_type="company",
            canonical_name=evidence.company.name,
            market=evidence.company.market,
            symbol=evidence.company.symbol,
            workspace_id=None,
        )
        entities.append(
            {
                "entity_type": "company",
                "canonical_name": evidence.company.name,
                "symbol": evidence.company.symbol,
                "market": evidence.company.market,
                "description": evidence.company.industry,
                "source_evidence_id": evidence_id,
                "confidence": 0.96,
                "metadata": {"source": "evidence_company"},
            }
        )
    if evidence.document:
        document = evidence.document
        document_key = _entity_key(
            entity_type="document",
            canonical_name=document.title,
            market=None,
            symbol=None,
            workspace_id=None,
        )
        entities.append(
            {
                "entity_type": "document",
                "canonical_name": document.title,
                "description": document.doc_type or "披露文件",
                "source_evidence_id": evidence_id,
                "confidence": 0.94,
                "metadata": {"document_id": document.id, "period": document.report_period, "source_url": document.source_url},
            }
        )
        if company_key:
            relations.append(
                {
                    "source_entity_key": company_key,
                    "target_entity_key": document_key,
                    "relation_type": "PUBLISHED",
                    "source_evidence_id": evidence_id,
                    "confidence": 0.9,
                    "metadata": {"reason": "evidence_document_company"},
                }
            )
    for metric_key, metric_name, pattern in METRIC_PATTERNS:
        if not pattern.search(text):
            continue
        entity_key = _entity_key(entity_type="metric", canonical_name=metric_name, market=None, symbol=None, workspace_id=None)
        entities.append(
            {
                "entity_type": "metric",
                "canonical_name": metric_name,
                "description": metric_key,
                "source_evidence_id": evidence_id,
                "confidence": 0.82,
                "metadata": {"metric_key": metric_key},
            }
        )
        if company_key:
            relations.append(
                {
                    "source_entity_key": company_key,
                    "target_entity_key": entity_key,
                    "relation_type": "HAS_METRIC",
                    "source_evidence_id": evidence_id,
                    "confidence": 0.78,
                    "metadata": {"reason": "metric_mentioned_in_evidence"},
                }
            )
        if document_key:
            relations.append(
                {
                    "source_entity_key": entity_key,
                    "target_entity_key": document_key,
                    "relation_type": "MENTIONED_IN",
                    "source_evidence_id": evidence_id,
                    "confidence": 0.76,
                    "metadata": {"reason": "metric_mentioned_in_document"},
                }
            )
    for risk_key, risk_name, pattern in RISK_PATTERNS:
        if not pattern.search(text):
            continue
        entity_key = _entity_key(entity_type="risk_event", canonical_name=risk_name, market=None, symbol=None, workspace_id=None)
        entities.append(
            {
                "entity_type": "risk_event",
                "canonical_name": risk_name,
                "description": risk_key,
                "source_evidence_id": evidence_id,
                "confidence": 0.76,
                "metadata": {"risk_key": risk_key},
            }
        )
        if company_key:
            relations.append(
                {
                    "source_entity_key": company_key,
                    "target_entity_key": entity_key,
                    "relation_type": "HAS_EVENT",
                    "source_evidence_id": evidence_id,
                    "confidence": 0.72,
                    "metadata": {"reason": "risk_mentioned_in_evidence"},
                }
            )
        if document_key:
            relations.append(
                {
                    "source_entity_key": entity_key,
                    "target_entity_key": document_key,
                    "relation_type": "MENTIONED_IN",
                    "source_evidence_id": evidence_id,
                    "confidence": 0.72,
                    "metadata": {"reason": "risk_mentioned_in_document"},
                }
            )
    return _dedupe_payloads(entities, key="entity_key"), relations


def _resolve_relation_payload(payload: dict[str, Any], entity_by_key: dict[str, Entity]) -> dict[str, Any]:
    return {
        "source_entity_id": entity_by_key[str(payload["source_entity_key"])].id,
        "target_entity_id": entity_by_key[str(payload["target_entity_key"])].id,
        "relation_type": payload["relation_type"],
        "source_evidence_id": payload.get("source_evidence_id"),
        "confidence": payload.get("confidence"),
        "metadata": payload.get("metadata"),
    }


def _dedupe_payloads(items: list[dict[str, Any]], *, key: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output = []
    for item in items:
        item_key = str(item.get(key) or _entity_key(
            entity_type=str(item.get("entity_type") or ""),
            canonical_name=str(item.get("canonical_name") or ""),
            market=item.get("market"),
            symbol=item.get("symbol"),
            workspace_id=item.get("workspace_id"),
        ))
        item["entity_key"] = item_key
        if item_key in seen:
            continue
        seen.add(item_key)
        output.append(item)
    return output


def _apply_entity_search(stmt: Select[tuple[Entity]], *, q: str | None) -> Select[tuple[Entity]]:
    if not q:
        return stmt
    needle = f"%{q.strip()}%"
    return stmt.where(
        or_(
            Entity.canonical_name.ilike(needle),
            Entity.symbol.ilike(needle),
            Entity.description.ilike(needle),
            Entity.entity_key.ilike(needle),
        )
    )


def _apply_relation_search(stmt: Select[tuple[EntityRelation]], *, q: str | None) -> Select[tuple[EntityRelation]]:
    if not q:
        return stmt
    needle = f"%{q.strip()}%"
    return stmt.where(
        or_(
            EntityRelation.source_entity.has(Entity.canonical_name.ilike(needle)),
            EntityRelation.target_entity.has(Entity.canonical_name.ilike(needle)),
            EntityRelation.relation_key.ilike(needle),
        )
    )


def _get_workspace_optional(session: Session, workspace_ref: int | str | None) -> Workspace | None:
    if workspace_ref in (None, ""):
        return None
    text = str(workspace_ref).strip()
    condition = Workspace.id == int(text) if text.isdigit() else Workspace.slug == text
    workspace = session.scalar(select(Workspace).where(condition))
    if workspace is None:
        raise EntityConflict(f"Workspace not found: {workspace_ref}")
    return workspace


def _entity_type(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    alias = {
        "stock": "ticker",
        "financial_metric": "metric",
        "risk": "risk_event",
        "event": "news_event",
        "peer": "peer_company",
    }.get(normalized, normalized)
    if alias not in ENTITY_TYPES:
        raise EntityConflict(f"Unsupported entity_type: {value}")
    return alias


def _relation_type(value: Any) -> str:
    normalized = str(value or "").strip().upper()
    if normalized not in RELATION_TYPES:
        raise EntityConflict(f"Unsupported relation_type: {value}")
    return normalized


def _entity_key(
    *,
    entity_type: str,
    canonical_name: str,
    market: Any,
    symbol: Any,
    workspace_id: Any,
) -> str:
    parts = [
        str(workspace_id or "global").lower(),
        _entity_type(entity_type),
        _norm(symbol or canonical_name),
        _norm(market or ""),
    ]
    return ":".join(parts)


def _relation_key(source_id: int, relation_type: str, target_id: int, evidence_id: str | None) -> str:
    evidence_part = _norm(evidence_id or "global")
    return f"{source_id}:{_relation_type(relation_type)}:{target_id}:{evidence_part}"


def _optional_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value).strip()


def _optional_upper(value: Any) -> str | None:
    text = _optional_string(value)
    return text.upper() if text else None


def _optional_float(value: Any, *, default: float) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _merge_dicts(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    merged.update(incoming)
    return merged


def _norm(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().lower())


def _dt(value: Any) -> str | None:
    return value.isoformat() if value is not None else None
