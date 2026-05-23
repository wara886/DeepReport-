"""Claim schema definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ClaimItem:
    """Claim unit linked to evidence ids and numeric values."""

    claim_id: str
    section_name: str
    claim_text: str
    evidence_ids: List[str] = field(default_factory=list)
    numeric_values: Dict[str, float] = field(default_factory=dict)
    risk_level: str = "unknown"
    confidence: float = 0.0
    notes: str = ""
    metric_lineage_ids: List[str] = field(default_factory=list)
    input_metric_lineage_ids: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ClaimItem":
        values = {str(k): float(v) for k, v in dict(data.get("numeric_values", {})).items()}
        return cls(
            claim_id=data["claim_id"],
            section_name=data["section_name"],
            claim_text=data["claim_text"],
            evidence_ids=list(data.get("evidence_ids", [])),
            numeric_values=values,
            risk_level=data.get("risk_level", "unknown"),
            confidence=float(data.get("confidence", 0.0)),
            notes=data.get("notes", ""),
            metric_lineage_ids=[str(value) for value in data.get("metric_lineage_ids", [])],
            input_metric_lineage_ids=[str(value) for value in data.get("input_metric_lineage_ids", [])],
        )

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "claim_id": self.claim_id,
            "section_name": self.section_name,
            "claim_text": self.claim_text,
            "evidence_ids": list(self.evidence_ids),
            "numeric_values": dict(self.numeric_values),
            "risk_level": self.risk_level,
            "confidence": self.confidence,
            "notes": self.notes,
        }
        if self.metric_lineage_ids:
            payload["metric_lineage_ids"] = list(self.metric_lineage_ids)
        if self.input_metric_lineage_ids:
            payload["input_metric_lineage_ids"] = list(self.input_metric_lineage_ids)
        return payload

