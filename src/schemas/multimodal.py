"""Multimodal artifact schemas and lineage checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ChartArtifact:
    """Chart artifact with explicit table, claim, and evidence lineage."""

    chart_id: str
    chart_type: str
    title: str
    input_table_ids: List[str] = field(default_factory=list)
    input_claim_ids: List[str] = field(default_factory=list)
    source_evidence_ids: List[str] = field(default_factory=list)
    source_fields: List[str] = field(default_factory=list)
    output_path: str = ""
    alt_text: str = ""
    period: str = ""
    unit: str = ""
    consistency_status: str = "unchecked"
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChartArtifact":
        return cls(
            chart_id=str(data["chart_id"]),
            chart_type=str(data["chart_type"]),
            title=str(data["title"]),
            input_table_ids=[str(item) for item in data.get("input_table_ids", [])],
            input_claim_ids=[str(item) for item in data.get("input_claim_ids", [])],
            source_evidence_ids=[str(item) for item in data.get("source_evidence_ids", [])],
            source_fields=[str(item) for item in data.get("source_fields", [])],
            output_path=str(data.get("output_path", "")),
            alt_text=str(data.get("alt_text", "")),
            period=str(data.get("period", "")),
            unit=str(data.get("unit", "")),
            consistency_status=str(data.get("consistency_status", "unchecked")),
            metadata=dict(data.get("metadata", {})),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chart_id": self.chart_id,
            "chart_type": self.chart_type,
            "title": self.title,
            "input_table_ids": list(self.input_table_ids),
            "input_claim_ids": list(self.input_claim_ids),
            "source_evidence_ids": list(self.source_evidence_ids),
            "source_fields": list(self.source_fields),
            "output_path": self.output_path,
            "alt_text": self.alt_text,
            "period": self.period,
            "unit": self.unit,
            "consistency_status": self.consistency_status,
            "metadata": dict(self.metadata),
        }

    def has_lineage(self) -> bool:
        return bool(self.input_table_ids and self.source_fields and (self.source_evidence_ids or self.input_claim_ids))


@dataclass
class VisualEvidence:
    """Visual evidence extracted from PDF pages, screenshots, or rendered pages."""

    evidence_id: str
    source_url: str
    image_path: str
    page_number: int | None = None
    ocr_text: str = ""
    linked_table_ids: List[str] = field(default_factory=list)
    linked_claim_ids: List[str] = field(default_factory=list)
    extraction_method: str = ""
    confidence: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VisualEvidence":
        raw_page = data.get("page_number")
        page_number = None if raw_page in {None, ""} else int(raw_page)
        return cls(
            evidence_id=str(data["evidence_id"]),
            source_url=str(data.get("source_url", "")),
            image_path=str(data.get("image_path", "")),
            page_number=page_number,
            ocr_text=str(data.get("ocr_text", "")),
            linked_table_ids=[str(item) for item in data.get("linked_table_ids", [])],
            linked_claim_ids=[str(item) for item in data.get("linked_claim_ids", [])],
            extraction_method=str(data.get("extraction_method", "")),
            confidence=float(data.get("confidence", 0.0) or 0.0),
            metadata=dict(data.get("metadata", {})),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "source_url": self.source_url,
            "image_path": self.image_path,
            "page_number": self.page_number,
            "ocr_text": self.ocr_text,
            "linked_table_ids": list(self.linked_table_ids),
            "linked_claim_ids": list(self.linked_claim_ids),
            "extraction_method": self.extraction_method,
            "confidence": self.confidence,
            "metadata": dict(self.metadata),
        }


def audit_chart_lineage(
    charts: List[Dict[str, Any]],
    tables: List[Dict[str, Any]],
    evidence_records: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Check whether charts can be traced back to tables and evidence."""

    table_ids = {str(item.get("table_id", "")) for item in tables if isinstance(item, dict)}
    evidence_ids = {
        str(item.get("evidence_id") or item.get("sample_id") or "")
        for item in evidence_records
        if isinstance(item, dict)
    }
    results: List[Dict[str, Any]] = []
    for raw_chart in charts:
        chart = ChartArtifact.from_dict(raw_chart)
        missing_tables = [table_id for table_id in chart.input_table_ids if table_id not in table_ids]
        missing_evidence = [evidence_id for evidence_id in chart.source_evidence_ids if evidence_id not in evidence_ids]
        errors: List[str] = []
        if not chart.input_table_ids:
            errors.append("missing_input_table_ids")
        if not chart.source_fields:
            errors.append("missing_source_fields")
        if not chart.source_evidence_ids and not chart.input_claim_ids:
            errors.append("missing_evidence_or_claim_lineage")
        if missing_tables:
            errors.append("missing_tables:" + ",".join(missing_tables))
        if missing_evidence:
            errors.append("missing_evidence:" + ",".join(missing_evidence))
        results.append(
            {
                "chart_id": chart.chart_id,
                "passed": not errors,
                "errors": errors,
            }
        )
    return {
        "passed": all(item["passed"] for item in results),
        "chart_count": len(results),
        "results": results,
    }
