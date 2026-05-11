"""Table artifact schema for company stock research reports."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class TableArtifact:
    """Structured table extracted from filings, APIs, or report computations."""

    table_id: str
    table_type: str
    rows: List[Dict[str, Any]] = field(default_factory=list)
    columns: List[str] = field(default_factory=list)
    source_evidence_id: str = ""
    source_url: str = ""
    source_page: str = ""
    period: str = ""
    currency: str = ""
    unit: str = ""
    extraction_method: str = ""
    confidence: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TableArtifact":
        return cls(
            table_id=str(data["table_id"]),
            table_type=str(data["table_type"]),
            rows=[dict(item) for item in data.get("rows", [])],
            columns=[str(item) for item in data.get("columns", [])],
            source_evidence_id=str(data.get("source_evidence_id", "")),
            source_url=str(data.get("source_url", "")),
            source_page=str(data.get("source_page", "")),
            period=str(data.get("period", "")),
            currency=str(data.get("currency", "")),
            unit=str(data.get("unit", "")),
            extraction_method=str(data.get("extraction_method", "")),
            confidence=float(data.get("confidence", 0.0) or 0.0),
            metadata=dict(data.get("metadata", {})),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "table_id": self.table_id,
            "table_type": self.table_type,
            "rows": [dict(item) for item in self.rows],
            "columns": list(self.columns),
            "source_evidence_id": self.source_evidence_id,
            "source_url": self.source_url,
            "source_page": self.source_page,
            "period": self.period,
            "currency": self.currency,
            "unit": self.unit,
            "extraction_method": self.extraction_method,
            "confidence": self.confidence,
            "metadata": dict(self.metadata),
        }

    def has_lineage(self) -> bool:
        return bool(self.source_evidence_id or self.source_url)
