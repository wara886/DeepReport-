"""Conversation memory and compression helpers for multi-agent report runs."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from typing import Any, Dict, List


DEFAULT_HARD_CONSTRAINTS = [
    "Only produce the requested company/stock research report type for this run.",
    "Every material factual claim must be backed by an explicit evidence_id citation.",
    "Do not invent numbers, dates, sources, ratings, or unsupported conclusions.",
    "Keep verifier feedback active during revisions until the final verification passes.",
    "Final artifacts must include Markdown, HTML, JSON, citations, charts, and compliance disclosure.",
]


@dataclass
class ConversationState:
    """Compact run-level memory shared across planning, writing, and verification."""

    session_id: str
    user_intent: str
    symbol: str
    period: str
    report_type: str = "company_stock_report"
    hard_constraints: List[str] = field(default_factory=list)
    pinned_facts: List[str] = field(default_factory=list)
    rejected_claims: List[str] = field(default_factory=list)
    verifier_feedback: List[str] = field(default_factory=list)
    open_questions: List[str] = field(default_factory=list)
    turns: List[Dict[str, Any]] = field(default_factory=list)

    def add_turn(self, role: str, content: str, metadata: Dict[str, Any] | None = None) -> None:
        text = _clean_text(content, limit=1200)
        if not text:
            return
        self.turns.append({"role": str(role), "content": text, "metadata": metadata or {}})
        self.turns = self.turns[-12:]

    def add_verifier_feedback(self, report: Dict[str, Any] | None) -> None:
        if not isinstance(report, dict):
            return
        for key in ["errors", "warnings", "fix_recommendations", "llm_errors", "llm_warnings"]:
            raw_items = report.get(key, [])
            if not isinstance(raw_items, list):
                continue
            for item in raw_items:
                text = _clean_text(str(item), limit=260)
                if not text:
                    continue
                _append_unique(self.verifier_feedback, f"{key}: {text}", max_items=14)
                if _looks_like_rejected_claim(text):
                    _append_unique(self.rejected_claims, text, max_items=10)
        revision_brief = _clean_text(str(report.get("revision_brief", "")), limit=700)
        if revision_brief:
            _append_unique(self.verifier_feedback, f"revision_brief: {revision_brief}", max_items=14)

    def context_brief(self, max_chars: int = 2400) -> str:
        sections = [
            ("User intent", [self.user_intent]),
            ("Run scope", [f"report_type={self.report_type}", f"symbol={self.symbol}", f"period={self.period}"]),
            ("Hard constraints", self.hard_constraints),
            ("Pinned facts", self.pinned_facts),
            ("Verifier feedback to keep active", self.verifier_feedback),
            ("Rejected or unsafe claims", self.rejected_claims),
            ("Open questions", self.open_questions),
        ]
        lines = ["[ConversationMemory]"]
        for title, items in sections:
            cleaned = [_clean_text(str(item), limit=280) for item in items if _clean_text(str(item), limit=280)]
            if not cleaned:
                continue
            lines.append(f"{title}:")
            lines.extend(f"- {item}" for item in cleaned[:10])
        return _truncate("\n".join(lines), max_chars=max_chars)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_intent": self.user_intent,
            "symbol": self.symbol,
            "period": self.period,
            "report_type": self.report_type,
            "hard_constraints": list(self.hard_constraints),
            "pinned_facts": list(self.pinned_facts),
            "rejected_claims": list(self.rejected_claims),
            "verifier_feedback": list(self.verifier_feedback),
            "open_questions": list(self.open_questions),
            "turns": list(self.turns),
            "context_brief": self.context_brief(),
        }


def build_initial_conversation_state(
    research_topic: str,
    requirements: List[str] | None,
    symbol: str,
    period: str,
    report_type: str = "company_stock_report",
) -> ConversationState:
    session_source = f"{research_topic}|{symbol}|{period}|{report_type}"
    session_id = hashlib.sha1(session_source.encode("utf-8")).hexdigest()[:12]
    state = ConversationState(
        session_id=session_id,
        user_intent=_clean_text(research_topic, limit=700),
        symbol=str(symbol),
        period=str(period),
        report_type=report_type,
        hard_constraints=list(DEFAULT_HARD_CONSTRAINTS),
        pinned_facts=[
            f"Target symbol: {symbol}",
            f"Target period: {period}",
            f"Report type: {report_type}",
        ],
    )
    for requirement in requirements or []:
        _append_unique(state.hard_constraints, _clean_text(str(requirement), limit=260), max_items=16)
    state.add_turn("user", research_topic, {"source": "run_request"})
    return state


def conversation_state_from_dict(data: Dict[str, Any] | None) -> ConversationState | None:
    if not isinstance(data, dict):
        return None
    state = ConversationState(
        session_id=str(data.get("session_id", "")),
        user_intent=str(data.get("user_intent", "")),
        symbol=str(data.get("symbol", "")),
        period=str(data.get("period", "")),
        report_type=str(data.get("report_type", "company_stock_report")),
        hard_constraints=_string_list(data.get("hard_constraints", [])),
        pinned_facts=_string_list(data.get("pinned_facts", [])),
        rejected_claims=_string_list(data.get("rejected_claims", [])),
        verifier_feedback=_string_list(data.get("verifier_feedback", [])),
        open_questions=_string_list(data.get("open_questions", [])),
        turns=[item for item in data.get("turns", []) if isinstance(item, dict)],
    )
    return state


def refresh_conversation_brief(state: Dict[str, Any], max_chars: int = 2400) -> str:
    memory = conversation_state_from_dict(state.get("conversation_context"))
    if not memory:
        return ""
    brief = memory.context_brief(max_chars=max_chars)
    state["conversation_context"] = memory.to_dict()
    state["conversation_brief"] = brief
    return brief


def absorb_verifier_feedback(state: Dict[str, Any]) -> str:
    memory = conversation_state_from_dict(state.get("conversation_context"))
    if not memory:
        return ""
    memory.add_verifier_feedback(state.get("verification_report", {}))
    state["conversation_context"] = memory.to_dict()
    state["conversation_brief"] = memory.context_brief()
    return state["conversation_brief"]


def _string_list(raw: Any) -> List[str]:
    if not isinstance(raw, list):
        return []
    return [_clean_text(str(item), limit=500) for item in raw if _clean_text(str(item), limit=500)]


def _append_unique(items: List[str], text: str, max_items: int) -> None:
    text = _clean_text(text, limit=500)
    if not text or text in items:
        return
    items.append(text)
    del items[:-max_items]


def _clean_text(text: str, limit: int = 500) -> str:
    cleaned = " ".join(str(text or "").replace("\n", " ").split())
    return cleaned[:limit].rstrip()


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 18].rstrip() + "\n...[compressed]"


def _looks_like_rejected_claim(text: str) -> bool:
    lowered = text.lower()
    markers = [
        "unsupported",
        "missing evidence",
        "missing citation",
        "not found in evidence",
        "not supported",
        "invent",
        "hallucinat",
        "缺少",
        "无证据",
        "未引用",
        "不支持",
    ]
    return any(marker in lowered for marker in markers)
