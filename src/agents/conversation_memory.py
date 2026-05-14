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
    """Layered run-level memory shared across planning, writing, and verification."""

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
    scope_memory: Dict[str, Any] = field(default_factory=dict)
    working_memory: Dict[str, Any] = field(default_factory=dict)
    evidence_memory: Dict[str, Any] = field(default_factory=dict)
    reflection_memory: Dict[str, Any] = field(default_factory=dict)
    domain_memory: Dict[str, Any] = field(default_factory=dict)

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
        self.reflection_memory = _build_reflection_memory(
            verifier_feedback=self.verifier_feedback,
            rejected_claims=self.rejected_claims,
            report=report,
            previous=self.reflection_memory,
        )

    def absorb_run_state(self, state: Dict[str, Any]) -> None:
        """Refresh structured memory layers from the current orchestrator state."""

        if not isinstance(state, dict):
            return
        evidence_records = state.get("evidence_records", [])
        claims = state.get("claims", [])
        analysis_artifacts = state.get("analysis_artifacts", {})
        self.working_memory = _build_working_memory(state=state, claims=claims, evidence_records=evidence_records)
        self.evidence_memory = _build_evidence_memory(
            evidence_records=evidence_records,
            claims=claims,
            analysis_artifacts=analysis_artifacts if isinstance(analysis_artifacts, dict) else {},
        )
        self.domain_memory = _build_domain_memory(
            symbol=str(state.get("symbol") or self.symbol),
            claims=claims,
            analysis_artifacts=analysis_artifacts if isinstance(analysis_artifacts, dict) else {},
        )
        self.reflection_memory = _build_reflection_memory(
            verifier_feedback=self.verifier_feedback,
            rejected_claims=self.rejected_claims,
            report=state.get("verification_report", {}) if isinstance(state.get("verification_report"), dict) else {},
            previous=self.reflection_memory,
        )

    def context_brief(self, max_chars: int = 2400) -> str:
        scope = self.scope_memory or {
            "user_intent": self.user_intent,
            "run_scope": f"report_type={self.report_type}; symbol={self.symbol}; period={self.period}",
            "report_type": self.report_type,
            "symbol": self.symbol,
            "period": self.period,
            "hard_constraints": self.hard_constraints,
            "pinned_facts": self.pinned_facts,
        }
        sections = [
            ("scope_memory", _memory_lines(scope)),
            ("working_memory", _memory_lines(self.working_memory)),
            ("evidence_memory", _memory_lines(self.evidence_memory)),
            ("reflection_memory", _memory_lines(self.reflection_memory)),
            ("domain_memory", _memory_lines(self.domain_memory)),
            ("open_questions", self.open_questions),
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
            "scope_memory": dict(self.scope_memory),
            "working_memory": dict(self.working_memory),
            "evidence_memory": dict(self.evidence_memory),
            "reflection_memory": dict(self.reflection_memory),
            "domain_memory": dict(self.domain_memory),
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
    state.scope_memory = {
        "user_intent": state.user_intent,
        "run_scope": f"report_type={state.report_type}; symbol={state.symbol}; period={state.period}",
        "report_type": state.report_type,
        "symbol": state.symbol,
        "period": state.period,
        "hard_constraints": list(state.hard_constraints),
        "pinned_facts": list(state.pinned_facts),
    }
    state.working_memory = {
        "pipeline_stage": "initialized",
        "evidence_count": 0,
        "claim_count": 0,
        "generated_sections": [],
    }
    state.evidence_memory = {
        "core_evidence_ids": [],
        "primary_source_ids": [],
        "market_snapshot_ids": [],
        "numeric_lineage": [],
    }
    state.reflection_memory = {
        "verifier_feedback": [],
        "rejected_claims": [],
        "revision_rounds": 0,
        "open_gap_count": 0,
    }
    state.domain_memory = _build_domain_memory(symbol=str(symbol), claims=[], analysis_artifacts={})
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
        scope_memory=_dict(data.get("scope_memory", {})),
        working_memory=_dict(data.get("working_memory", {})),
        evidence_memory=_dict(data.get("evidence_memory", {})),
        reflection_memory=_dict(data.get("reflection_memory", {})),
        domain_memory=_dict(data.get("domain_memory", {})),
    )
    if not state.scope_memory:
        state.scope_memory = {
            "user_intent": state.user_intent,
            "run_scope": f"report_type={state.report_type}; symbol={state.symbol}; period={state.period}",
            "report_type": state.report_type,
            "symbol": state.symbol,
            "period": state.period,
            "hard_constraints": list(state.hard_constraints),
            "pinned_facts": list(state.pinned_facts),
        }
    return state


def refresh_conversation_brief(state: Dict[str, Any], max_chars: int = 2400) -> str:
    memory = conversation_state_from_dict(state.get("conversation_context"))
    if not memory:
        return ""
    memory.absorb_run_state(state)
    brief = memory.context_brief(max_chars=max_chars)
    state["conversation_context"] = memory.to_dict()
    state["conversation_brief"] = brief
    return brief


def refresh_conversation_memory_from_state(state: Dict[str, Any], max_chars: int = 2400) -> str:
    """Update layered memory from the current pipeline state and return the brief."""

    return refresh_conversation_brief(state=state, max_chars=max_chars)


def absorb_verifier_feedback(state: Dict[str, Any]) -> str:
    memory = conversation_state_from_dict(state.get("conversation_context"))
    if not memory:
        return ""
    memory.add_verifier_feedback(state.get("verification_report", {}))
    memory.absorb_run_state(state)
    state["conversation_context"] = memory.to_dict()
    state["conversation_brief"] = memory.context_brief()
    return state["conversation_brief"]


def _build_working_memory(state: Dict[str, Any], claims: Any, evidence_records: Any) -> Dict[str, Any]:
    claim_list = [item for item in claims if isinstance(item, dict)] if isinstance(claims, list) else []
    evidence_list = [item for item in evidence_records if isinstance(item, dict)] if isinstance(evidence_records, list) else []
    sections = sorted({str(item.get("section_name", "")) for item in claim_list if str(item.get("section_name", ""))})
    return {
        "pipeline_stage": _infer_pipeline_stage(state),
        "evidence_count": len(evidence_list),
        "claim_count": len(claim_list),
        "generated_sections": sections[:16],
        "chart_count": len(state.get("charts", [])) if isinstance(state.get("charts"), list) else 0,
        "verification_passed": bool(state.get("verification_report", {}).get("passed", False))
        if isinstance(state.get("verification_report"), dict) else False,
    }


def _build_evidence_memory(
    evidence_records: Any,
    claims: Any,
    analysis_artifacts: Dict[str, Any],
) -> Dict[str, Any]:
    records = [item for item in evidence_records if isinstance(item, dict)] if isinstance(evidence_records, list) else []
    claim_list = [item for item in claims if isinstance(item, dict)] if isinstance(claims, list) else []
    cited_ids: List[str] = []
    for claim in claim_list:
        for evidence_id in claim.get("evidence_ids", []) if isinstance(claim.get("evidence_ids", []), list) else []:
            _append_unique(cited_ids, str(evidence_id), max_items=12)
    primary_ids = [
        str(record.get("evidence_id") or record.get("sample_id") or "")
        for record in records
        if str(record.get("authority_level") or record.get("source_authority") or "").lower() in {"primary", "sec", "company"}
        or str(record.get("source_type") or "").lower() in {"financials", "filing", "company_ir"}
    ]
    market_ids = [
        str(record.get("evidence_id") or record.get("sample_id") or "")
        for record in records
        if str(record.get("source_type") or "").lower() in {"market", "market_api"}
    ]
    numeric_lineage = []
    metrics = analysis_artifacts.get("financial_metrics", {}) if isinstance(analysis_artifacts, dict) else {}
    if isinstance(metrics, dict):
        for key in ["metric_count", "primary_source_metric_count", "source_record_count"]:
            if key in metrics:
                numeric_lineage.append(f"{key}={metrics.get(key)}")
    return {
        "core_evidence_ids": cited_ids[:12],
        "primary_source_ids": [item for item in primary_ids if item][:8],
        "market_snapshot_ids": [item for item in market_ids if item][:4],
        "numeric_lineage": numeric_lineage[:8],
    }


def _build_reflection_memory(
    verifier_feedback: List[str],
    rejected_claims: List[str],
    report: Dict[str, Any] | None,
    previous: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    previous = previous or {}
    report = report or {}
    gaps = report.get("evidence_gaps", []) if isinstance(report.get("evidence_gaps"), list) else []
    return {
        "verifier_feedback": list(verifier_feedback[-8:]),
        "rejected_claims": list(rejected_claims[-8:]),
        "revision_rounds": previous.get("revision_rounds", 0),
        "open_gap_count": len(gaps),
        "last_passed": bool(report.get("passed", False)) if report else bool(previous.get("last_passed", False)),
    }


def _build_domain_memory(symbol: str, claims: Any, analysis_artifacts: Dict[str, Any]) -> Dict[str, Any]:
    symbol = str(symbol or "").upper()
    claim_list = [item for item in claims if isinstance(item, dict)] if isinstance(claims, list) else []
    has_peer = any(str(item.get("section_name")) == "peer_compare" for item in claim_list)
    has_fcf = any("free_cash_flow" in str(item.get("numeric_values", {})) for item in claim_list)
    valuation = analysis_artifacts.get("valuation", {}) if isinstance(analysis_artifacts, dict) else {}
    rules = []
    if symbol in {"JPM", "BAC", "WFC", "C", "GS", "MS"}:
        rules.append("Bank valuation primary methods: P/B + DDM + supporting P/E; treat FCF DCF as limited.")
        rules.append("Bank cash flow needs balance-sheet context; do not read OCF mechanically as industrial FCF.")
    if symbol in {"META", "GOOGL", "NFLX", "DIS", "T"}:
        rules.append("Communication services peer comparison must distinguish core ad-platform peers from extended media/telecom references.")
    if symbol == "META" or has_fcf:
        rules.append("FCF wording must follow free_cash_flow_methodology; distinguish simplified OCF - CapEx from lease-adjusted definitions.")
    if has_peer:
        rules.append("Peer compare must name core peers, extended references, fiscal-period alignment, and selection rationale.")
    if isinstance(valuation, dict) and valuation:
        rules.append("Valuation claims must preserve model assumptions and market snapshot timestamp.")
    if not rules:
        rules.append("Use evidence-backed company-report rules; preserve numeric lineage and citation discipline.")
    return {"rules": rules[:10]}


def _memory_lines(memory: Dict[str, Any] | List[str] | Any) -> List[str]:
    if isinstance(memory, list):
        return [str(item) for item in memory]
    if not isinstance(memory, dict):
        return []
    lines: List[str] = []
    for key, value in memory.items():
        if isinstance(value, list):
            if not value:
                continue
            lines.append(f"{key}: " + "; ".join(_clean_text(str(item), limit=160) for item in value[:8]))
        elif isinstance(value, dict):
            if value:
                lines.append(f"{key}: {value}")
        elif value not in (None, "", []):
            lines.append(f"{key}: {value}")
    return lines


def _infer_pipeline_stage(state: Dict[str, Any]) -> str:
    if state.get("verification_report"):
        return "verified"
    if state.get("markdown") or state.get("html"):
        return "drafted"
    if state.get("claims"):
        return "analyzed"
    if state.get("evidence_records"):
        return "evidence_normalized"
    if state.get("evidence_candidates"):
        return "researched"
    return "initialized"


def _dict(raw: Any) -> Dict[str, Any]:
    return dict(raw) if isinstance(raw, dict) else {}


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
