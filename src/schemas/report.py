"""Report section and document schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from src.schemas.chart import ChartSpec
from src.schemas.claim import ClaimItem


@dataclass
class ReportSection:
    """One report section with claims, charts, markdown body, and citations."""

    section_name: str
    section_title: str
    claims: List[ClaimItem] = field(default_factory=list)
    charts: List[ChartSpec] = field(default_factory=list)
    body_markdown: str = ""
    citations: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReportSection":
        claims = [ClaimItem.from_dict(item) for item in data.get("claims", [])]
        charts = [ChartSpec.from_dict(item) for item in data.get("charts", [])]
        return cls(
            section_name=data["section_name"],
            section_title=data["section_title"],
            claims=claims,
            charts=charts,
            body_markdown=data.get("body_markdown", ""),
            citations=list(data.get("citations", [])),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "section_name": self.section_name,
            "section_title": self.section_title,
            "claims": [item.to_dict() for item in self.claims],
            "charts": [item.to_dict() for item in self.charts],
            "body_markdown": self.body_markdown,
            "citations": list(self.citations),
        }


@dataclass
class ReportDocument:
    """Top-level report document schema."""

    report_id: str
    symbol: str
    period: str
    report_type: str
    sections: List[ReportSection] = field(default_factory=list)
    generated_at: str = ""
    export_paths: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReportDocument":
        sections = [ReportSection.from_dict(item) for item in data.get("sections", [])]
        return cls(
            report_id=data["report_id"],
            symbol=data["symbol"],
            period=data["period"],
            report_type=data["report_type"],
            sections=sections,
            generated_at=data.get("generated_at", ""),
            export_paths=dict(data.get("export_paths", {})),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "symbol": self.symbol,
            "period": self.period,
            "report_type": self.report_type,
            "sections": [item.to_dict() for item in self.sections],
            "generated_at": self.generated_at,
            "export_paths": dict(self.export_paths),
        }

