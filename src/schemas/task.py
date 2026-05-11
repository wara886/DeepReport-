"""Task schema for pipeline scheduling."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ReportTask:
    """Pipeline task definition used by orchestration and execution layers."""

    task_id: str
    symbol: str
    period: str
    report_type: str
    stage_name: str
    requirements: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReportTask":
        return cls(
            task_id=data["task_id"],
            symbol=data["symbol"],
            period=data["period"],
            report_type=data["report_type"],
            stage_name=data["stage_name"],
            requirements=list(data.get("requirements", [])),
            metadata=dict(data.get("metadata", {})),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "symbol": self.symbol,
            "period": self.period,
            "report_type": self.report_type,
            "stage_name": self.stage_name,
            "requirements": list(self.requirements),
            "metadata": dict(self.metadata),
        }

