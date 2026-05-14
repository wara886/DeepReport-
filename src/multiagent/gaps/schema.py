"""Canonical gap schema for verifier-driven targeted rework."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List


class GapType(str, Enum):
    EVIDENCE_GAP = "EVIDENCE_GAP"
    NUMERIC_GAP = "NUMERIC_GAP"
    VALUATION_GAP = "VALUATION_GAP"
    CITATION_GAP = "CITATION_GAP"
    RISK_GAP = "RISK_GAP"
    PEER_GAP = "PEER_GAP"
    FORMAT_GAP = "FORMAT_GAP"
    COMPLIANCE_GAP = "COMPLIANCE_GAP"
    SYMBOL_PERIOD_MISMATCH = "SYMBOL_PERIOD_MISMATCH"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"


class GapStatus(str, Enum):
    OPEN = "open"
    ROUTED = "routed"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"


class GapSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class GapItem:
    gap_id: str
    gap_type: GapType
    severity: GapSeverity
    detected_by: str
    related_claim_ids: List[str] = field(default_factory=list)
    related_evidence_ids: List[str] = field(default_factory=list)
    section: str = ""
    description: str = ""
    recommended_action: str = ""
    status: GapStatus = GapStatus.OPEN
    routed_to_agents: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: now_iso())
    resolved_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gap_id": self.gap_id,
            "gap_type": self.gap_type.value,
            "severity": self.severity.value,
            "detected_by": self.detected_by,
            "related_claim_ids": list(self.related_claim_ids),
            "related_evidence_ids": list(self.related_evidence_ids),
            "section": self.section,
            "description": self.description,
            "recommended_action": self.recommended_action,
            "status": self.status.value,
            "routed_to_agents": list(self.routed_to_agents),
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "GapItem":
        return cls(
            gap_id=str(payload.get("gap_id", "")),
            gap_type=parse_gap_type(payload.get("gap_type")),
            severity=parse_severity(payload.get("severity")),
            detected_by=str(payload.get("detected_by", "VerifierAgent")),
            related_claim_ids=_str_list(payload.get("related_claim_ids", [])),
            related_evidence_ids=_str_list(payload.get("related_evidence_ids", [])),
            section=str(payload.get("section", "")),
            description=str(payload.get("description", "")),
            recommended_action=str(payload.get("recommended_action", "")),
            status=parse_status(payload.get("status")),
            routed_to_agents=_str_list(payload.get("routed_to_agents", [])),
            created_at=str(payload.get("created_at") or now_iso()),
            resolved_at=str(payload.get("resolved_at", "")),
        )

    def with_route(self, agents: List[str]) -> "GapItem":
        return GapItem(
            gap_id=self.gap_id,
            gap_type=self.gap_type,
            severity=self.severity,
            detected_by=self.detected_by,
            related_claim_ids=list(self.related_claim_ids),
            related_evidence_ids=list(self.related_evidence_ids),
            section=self.section,
            description=self.description,
            recommended_action=self.recommended_action,
            status=GapStatus.ROUTED,
            routed_to_agents=list(agents),
            created_at=self.created_at,
            resolved_at=self.resolved_at,
        )

    def with_status(self, status: GapStatus, resolved_at: str = "") -> "GapItem":
        return GapItem(
            gap_id=self.gap_id,
            gap_type=self.gap_type,
            severity=self.severity,
            detected_by=self.detected_by,
            related_claim_ids=list(self.related_claim_ids),
            related_evidence_ids=list(self.related_evidence_ids),
            section=self.section,
            description=self.description,
            recommended_action=self.recommended_action,
            status=status,
            routed_to_agents=list(self.routed_to_agents),
            created_at=self.created_at,
            resolved_at=resolved_at,
        )


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_gap_type(value: Any) -> GapType:
    text = str(value or "").strip()
    aliases = {
        "missing_primary_evidence": GapType.EVIDENCE_GAP,
        "missing_evidence": GapType.EVIDENCE_GAP,
        "citation_missing": GapType.CITATION_GAP,
        "uncited_evidence": GapType.CITATION_GAP,
        "numeric_missing": GapType.NUMERIC_GAP,
        "numeric_inconsistent": GapType.NUMERIC_GAP,
        "valuation_formula_error": GapType.VALUATION_GAP,
        "source_conflict": GapType.SOURCE_CONFLICT,
        "inconsistent_source": GapType.SOURCE_CONFLICT,
        "conflicting_evidence": GapType.SOURCE_CONFLICT,
        "multimodal_conflict": GapType.FORMAT_GAP,
        "entity_or_period_mismatch": GapType.SYMBOL_PERIOD_MISMATCH,
    }
    if text in aliases:
        return aliases[text]
    try:
        return GapType(text)
    except ValueError:
        upper = text.upper()
        return GapType(upper) if upper in GapType.__members__ else GapType.FORMAT_GAP


def parse_status(value: Any) -> GapStatus:
    text = str(value or GapStatus.OPEN.value).strip().lower()
    for status in GapStatus:
        if status.value == text:
            return status
    return GapStatus.OPEN


def parse_severity(value: Any) -> GapSeverity:
    text = str(value or GapSeverity.MEDIUM.value).strip().lower()
    for severity in GapSeverity:
        if severity.value == text:
            return severity
    return GapSeverity.MEDIUM


def _str_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]
