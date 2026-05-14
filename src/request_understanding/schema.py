"""Structured schema for natural-language financial research requests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class ResolvedEntity:
    company_name: str = ""
    symbol: str = ""
    market: str = ""
    confidence: float = 0.0
    candidates: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "company_name": self.company_name,
            "symbol": self.symbol,
            "market": self.market,
            "confidence": round(float(self.confidence), 3),
            "candidates": list(self.candidates),
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any] | None) -> "ResolvedEntity":
        data = payload or {}
        return cls(
            company_name=str(data.get("company_name", "")),
            symbol=str(data.get("symbol", "")).upper(),
            market=str(data.get("market", "")),
            confidence=float(data.get("confidence", 0.0) or 0.0),
            candidates=list(data.get("candidates", [])) if isinstance(data.get("candidates", []), list) else [],
        )


@dataclass(frozen=True)
class PeriodSpec:
    type: str = "latest_quarter"
    explicit_start_date: str = ""
    explicit_end_date: str = ""
    granularity: str = "quarter"

    def to_dict(self) -> Dict[str, str]:
        return {
            "type": self.type,
            "explicit_start_date": self.explicit_start_date,
            "explicit_end_date": self.explicit_end_date,
            "granularity": self.granularity,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any] | None) -> "PeriodSpec":
        data = payload or {}
        return cls(
            type=str(data.get("type", "latest_quarter")),
            explicit_start_date=str(data.get("explicit_start_date", "")),
            explicit_end_date=str(data.get("explicit_end_date", "")),
            granularity=str(data.get("granularity", "quarter")),
        )


@dataclass(frozen=True)
class OutputPreferences:
    language: str = "zh"
    format: str = "markdown_html_json"
    depth: str = "deep"

    def to_dict(self) -> Dict[str, str]:
        return {"language": self.language, "format": self.format, "depth": self.depth}

    @classmethod
    def from_dict(cls, payload: Dict[str, Any] | None) -> "OutputPreferences":
        data = payload or {}
        return cls(
            language=str(data.get("language", "zh")),
            format=str(data.get("format", "markdown_html_json")),
            depth=str(data.get("depth", "deep")),
        )


@dataclass(frozen=True)
class AttachmentSpec:
    optional: bool = True
    files: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"optional": bool(self.optional), "files": list(self.files)}

    @classmethod
    def from_dict(cls, payload: Dict[str, Any] | None) -> "AttachmentSpec":
        data = payload or {}
        files = data.get("files", [])
        return cls(optional=bool(data.get("optional", True)), files=list(files) if isinstance(files, list) else [])


@dataclass(frozen=True)
class ResearchRequest:
    original_query: str
    resolved_entity: ResolvedEntity = field(default_factory=ResolvedEntity)
    report_type: str = "company_research"
    period: PeriodSpec = field(default_factory=PeriodSpec)
    focus_areas: List[str] = field(default_factory=list)
    output_preferences: OutputPreferences = field(default_factory=OutputPreferences)
    attachments: AttachmentSpec = field(default_factory=AttachmentSpec)
    clarification_needed: bool = False
    clarification_questions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_query": self.original_query,
            "resolved_entity": self.resolved_entity.to_dict(),
            "report_type": self.report_type,
            "period": self.period.to_dict(),
            "focus_areas": list(self.focus_areas),
            "output_preferences": self.output_preferences.to_dict(),
            "attachments": self.attachments.to_dict(),
            "clarification_needed": bool(self.clarification_needed),
            "clarification_questions": list(self.clarification_questions),
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ResearchRequest":
        return cls(
            original_query=str(payload.get("original_query", "")),
            resolved_entity=ResolvedEntity.from_dict(payload.get("resolved_entity") if isinstance(payload.get("resolved_entity"), dict) else {}),
            report_type=str(payload.get("report_type", "company_research")),
            period=PeriodSpec.from_dict(payload.get("period") if isinstance(payload.get("period"), dict) else {}),
            focus_areas=[str(item) for item in payload.get("focus_areas", [])] if isinstance(payload.get("focus_areas", []), list) else [],
            output_preferences=OutputPreferences.from_dict(
                payload.get("output_preferences") if isinstance(payload.get("output_preferences"), dict) else {}
            ),
            attachments=AttachmentSpec.from_dict(payload.get("attachments") if isinstance(payload.get("attachments"), dict) else {}),
            clarification_needed=bool(payload.get("clarification_needed", False)),
            clarification_questions=[str(item) for item in payload.get("clarification_questions", [])]
            if isinstance(payload.get("clarification_questions", []), list)
            else [],
        )

    def planner_topic(self) -> str:
        entity = self.resolved_entity
        focus = "、".join(self.focus_areas) if self.focus_areas else "基本面、财务表现、估值、风险"
        return f"{entity.company_name or entity.symbol}（{entity.symbol}）{self.period.type} {self.report_type}：{focus}"

    def planner_requirements(self) -> List[str]:
        requirements = [
            f"报告类型：{self.report_type}",
            f"时间范围：{self.period.type}，粒度：{self.period.granularity}",
            "重点关注：" + ("、".join(self.focus_areas) if self.focus_areas else "基本面、财务、估值、风险"),
            f"输出偏好：language={self.output_preferences.language}, format={self.output_preferences.format}, depth={self.output_preferences.depth}",
            "上传文件是可选补充证据；公开公司研报优先使用可信公开来源。",
        ]
        if self.attachments.files:
            requirements.append(f"用户上传了 {len(self.attachments.files)} 个可选证据文件，作为补充证据使用。")
        return requirements

    @property
    def symbol(self) -> str:
        return self.resolved_entity.symbol

    @property
    def market(self) -> str:
        return self.resolved_entity.market

    @property
    def period_label(self) -> str:
        return self.period.type


def normalize_structured_request(payload: Dict[str, Any]) -> ResearchRequest:
    if "resolved_entity" in payload:
        return ResearchRequest.from_dict(payload)
    company_name = str(payload.get("company_name", ""))
    symbol = str(payload.get("symbol", "")).upper()
    market = str(payload.get("market", ""))
    query = str(payload.get("original_query") or payload.get("topic") or "")
    period_payload = payload.get("period") if isinstance(payload.get("period"), dict) else {"type": str(payload.get("period", "latest_quarter"))}
    return ResearchRequest(
        original_query=query,
        resolved_entity=ResolvedEntity(company_name=company_name, symbol=symbol, market=market, confidence=1.0 if symbol else 0.0),
        report_type=str(payload.get("report_type", "company_research")),
        period=PeriodSpec.from_dict(period_payload),
        focus_areas=[str(item) for item in payload.get("focus_areas", [])] if isinstance(payload.get("focus_areas", []), list) else [],
        output_preferences=OutputPreferences.from_dict(payload.get("output_preferences") if isinstance(payload.get("output_preferences"), dict) else {}),
        attachments=AttachmentSpec.from_dict(payload.get("attachments") if isinstance(payload.get("attachments"), dict) else {}),
        clarification_needed=not bool(symbol),
        clarification_questions=[] if symbol else ["请确认要研究的上市公司或股票代码。"],
    )
