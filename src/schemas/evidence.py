"""Evidence schema for claim-first report generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class EvidenceItem:
    """Normalized evidence record used across data and report modules."""

    evidence_id: str
    source_type: str
    title: str
    source_url: str
    publish_time: str
    content: str
    symbol: str
    period: str
    trust_level: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvidenceItem":
        return cls(
            evidence_id=data["evidence_id"],
            source_type=data["source_type"],
            title=data["title"],
            source_url=data["source_url"],
            publish_time=data["publish_time"],
            content=data["content"],
            symbol=data["symbol"],
            period=data["period"],
            trust_level=data["trust_level"],
            metadata=dict(data.get("metadata", {})),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "source_type": self.source_type,
            "title": self.title,
            "source_url": self.source_url,
            "publish_time": self.publish_time,
            "content": self.content,
            "symbol": self.symbol,
            "period": self.period,
            "trust_level": self.trust_level,
            "metadata": dict(self.metadata),
        }

