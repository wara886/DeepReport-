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
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "section_name": self.section_name,
            "claim_text": self.claim_text,
            "evidence_ids": list(self.evidence_ids),
            "numeric_values": dict(self.numeric_values),
            "risk_level": self.risk_level,
            "confidence": self.confidence,
            "notes": self.notes,
        }

