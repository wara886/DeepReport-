"""Chart specification schema."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ChartSpec:
    """Chart metadata and source binding for report rendering."""

    chart_id: str
    chart_type: str
    title: str
    source_tables: List[str] = field(default_factory=list)
    source_fields: List[str] = field(default_factory=list)
    output_path: str = ""
    caption: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChartSpec":
        return cls(
            chart_id=data["chart_id"],
            chart_type=data["chart_type"],
            title=data["title"],
            source_tables=list(data.get("source_tables", [])),
            source_fields=list(data.get("source_fields", [])),
            output_path=data.get("output_path", ""),
            caption=data.get("caption", ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chart_id": self.chart_id,
            "chart_type": self.chart_type,
            "title": self.title,
            "source_tables": list(self.source_tables),
            "source_fields": list(self.source_fields),
            "output_path": self.output_path,
            "caption": self.caption,
        }

