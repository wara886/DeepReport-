"""Static skill registry for planner and router context.

Skills are compact capability summaries. They help the planner/router decide
which specialist flow to use, but they do not execute tools or replace
evidence/citation gates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List

from src.utils.config import load_config


@dataclass(frozen=True)
class SkillSpec:
    """A planner-visible skill summary."""

    name: str
    description: str
    agent_types: List[str] = field(default_factory=list)
    trigger_terms: List[str] = field(default_factory=list)
    tool_names: List[str] = field(default_factory=list)
    input_summary: str = ""
    output_summary: str = ""
    guardrails: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "agent_types": list(self.agent_types),
            "trigger_terms": list(self.trigger_terms),
            "tool_names": list(self.tool_names),
            "input_summary": self.input_summary,
            "output_summary": self.output_summary,
            "guardrails": list(self.guardrails),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SkillSpec":
        return cls(
            name=str(data["name"]),
            description=str(data.get("description", "")),
            agent_types=_string_list(data.get("agent_types", [])),
            trigger_terms=_string_list(data.get("trigger_terms", [])),
            tool_names=_string_list(data.get("tool_names", [])),
            input_summary=str(data.get("input_summary", "")),
            output_summary=str(data.get("output_summary", "")),
            guardrails=_string_list(data.get("guardrails", [])),
            metadata=dict(data.get("metadata", {})) if isinstance(data.get("metadata", {}), dict) else {},
        )


class SkillRegistry:
    """Register, select, and render compact skill summaries."""

    def __init__(self, skills: Iterable[SkillSpec] | None = None):
        self._skills: Dict[str, SkillSpec] = {}
        for skill in skills or []:
            self.register(skill)

    def register(self, skill: SkillSpec) -> None:
        if skill.name in self._skills:
            raise ValueError(f"skill already registered: {skill.name}")
        self._skills[skill.name] = skill

    def names(self) -> List[str]:
        return sorted(self._skills.keys())

    def get(self, name: str) -> SkillSpec:
        if name not in self._skills:
            raise KeyError(f"skill not found: {name}")
        return self._skills[name]

    def select(
        self,
        query: str = "",
        task_type: str = "",
        max_items: int = 4,
    ) -> List[SkillSpec]:
        """Select relevant skills for a planner/router query."""

        task = str(task_type or "").lower().strip()
        text = str(query or "").lower()
        scored: List[tuple[int, str, SkillSpec]] = []
        for skill in self._skills.values():
            score = 0
            agent_types = {item.lower() for item in skill.agent_types}
            if task and task in agent_types:
                score += 5
            if task == "planning" and agent_types:
                score += 2
            for term in skill.trigger_terms:
                term_text = str(term).lower().strip()
                if term_text and term_text in text:
                    score += 2
            for tool_name in skill.tool_names:
                tool_text = str(tool_name).lower().strip()
                if tool_text and tool_text in text:
                    score += 1
            if score > 0:
                scored.append((score, skill.name, skill))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [item[2] for item in scored[: max(0, int(max_items))]]

    def render_brief(
        self,
        query: str = "",
        task_type: str = "",
        max_items: int = 4,
        max_chars: int = 1600,
    ) -> str:
        skills = self.select(query=query, task_type=task_type, max_items=max_items)
        if not skills:
            return ""
        lines = [
            "[SkillRegistry]",
            "Planner/router capability hints only. Skills do not replace tool execution, evidence, citations, or verifier gates.",
        ]
        for skill in skills:
            tool_text = ", ".join(skill.tool_names[:5])
            guardrail_text = "; ".join(skill.guardrails[:2])
            parts = [
                skill.description,
                f"inputs: {skill.input_summary}" if skill.input_summary else "",
                f"outputs: {skill.output_summary}" if skill.output_summary else "",
                f"tools: {tool_text}" if tool_text else "",
                f"guardrails: {guardrail_text}" if guardrail_text else "",
            ]
            lines.append(f"- {skill.name}: " + " | ".join(part for part in parts if part))
        return _truncate("\n".join(lines), int(max_chars))

    def to_dict(self) -> Dict[str, Any]:
        return {"skills": [self._skills[name].to_dict() for name in self.names()]}


def build_financial_skill_registry(config_path: str | Path | None = "configs/skill_registry.yaml") -> SkillRegistry:
    """Build the financial skill registry, preferring YAML config when present."""

    if config_path:
        configured = _load_configured_skills(config_path)
        if configured:
            return SkillRegistry(configured)

    return SkillRegistry(
        [
            SkillSpec(
                name="evidence_discovery",
                description="Find company filings, financial records, market snapshots, and recent news for a target company/period.",
                agent_types=["planning", "deep_researcher", "browser"],
                trigger_terms=["evidence", "source", "filing", "news", "market", "citation", "research"],
                tool_names=["retrieve_local_evidence", "fetch_yahoo_market_snapshot"],
                input_summary="symbol, period, research topic, source preferences, ranking mode",
                output_summary="ranked evidence candidates and citation-ready evidence records",
                guardrails=[
                    "Prefer current primary or high-trust evidence for factual claims.",
                    "Memory notes can guide search terms but are never evidence.",
                ],
            ),
            SkillSpec(
                name="financial_statement_analysis",
                description="Compute financial ratios, trend coverage, three-statement views, peer context, and valuation artifacts.",
                agent_types=["planning", "deep_analyze"],
                trigger_terms=["ratio", "margin", "cash flow", "valuation", "peer", "trend", "financial", "three statement"],
                tool_names=[
                    "calculate_financial_ratios",
                    "build_trend_features",
                    "build_three_statement_view",
                    "build_peer_comparison",
                    "perform_company_valuation",
                ],
                input_summary="citation-ready evidence records plus symbol/period/raw_data_root",
                output_summary="evidence-backed claims, tables, metrics, valuation model, and sensitivity artifacts",
                guardrails=[
                    "Every numeric claim must retain evidence_ids and lineage.",
                    "Use fallback notes when peer or valuation inputs are incomplete.",
                ],
            ),
            SkillSpec(
                name="report_assembly",
                description="Assemble claims into the required Chinese research report sections with citations, charts, and disclosures.",
                agent_types=["planning", "final_answer"],
                trigger_terms=["report", "markdown", "html", "section", "citation", "chart", "disclosure"],
                tool_names=["render_all_charts", "attach_charts_to_report"],
                input_summary="claims, evidence records, chart/table artifacts, revision brief",
                output_summary="Markdown, HTML, JSON report payloads with references and compliance disclosure",
                guardrails=[
                    "Do not invent unsupported sections or ratings.",
                    "Use evidence_id citations after factual claims.",
                ],
            ),
            SkillSpec(
                name="verification_rework",
                description="Verify claim support, citation coverage, chart/table lineage, and route repair work for open gaps.",
                agent_types=["planning", "verifier"],
                trigger_terms=["verify", "verification", "gap", "rework", "audit", "scorecard", "lineage"],
                tool_names=[],
                input_summary="draft report, claims, evidence, charts, tables, valuation artifacts",
                output_summary="verification report, evidence gaps, revision brief, and scorecard inputs",
                guardrails=[
                    "Fail unsupported numbers even when prose looks plausible.",
                    "Open gaps route back to research/analyze/final rather than being hidden.",
                ],
            ),
            SkillSpec(
                name="industry_research",
                description="Generate an industry research report from company evidence, peer context, sector metadata, and risk signals.",
                agent_types=["planning", "industry_research"],
                trigger_terms=["industry", "sector", "peer", "competition", "supply chain", "行业", "竞争"],
                tool_names=["build_peer_comparison"],
                input_summary="company run summary, evidence records, claims, peer context",
                output_summary="industry report markdown/json with sector structure and risks",
                guardrails=[
                    "Mark missing standalone industry datasets as limitations.",
                    "Tie company-specific industry statements back to evidence ids when available.",
                ],
            ),
            SkillSpec(
                name="macro_context",
                description="Generate a macro context report for valuation, demand, rates, liquidity, FX, and policy transmission.",
                agent_types=["planning", "macro_research"],
                trigger_terms=["macro", "rate", "inflation", "policy", "liquidity", "fx", "宏观", "利率"],
                tool_names=[],
                input_summary="period, company summary, market evidence, verification context",
                output_summary="macro report markdown/json with transmission channels and risk caveats",
                guardrails=[
                    "Do not claim current macro statistics unless explicit evidence is present.",
                    "Separate directional transmission logic from evidenced facts.",
                ],
            ),
        ]
    )


def _load_configured_skills(config_path: str | Path) -> List[SkillSpec]:
    path = Path(config_path)
    if not path.exists():
        return []
    payload = load_config(path)
    raw_skills = payload.get("skills", []) if isinstance(payload, dict) else []
    if not isinstance(raw_skills, list):
        return []
    skills: List[SkillSpec] = []
    for item in raw_skills:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        skills.append(SkillSpec.from_dict(item))
    return skills


def _string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return [str(value)] if value not in (None, "") else []
    return [str(item) for item in value if str(item).strip()]


def _truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 18].rstrip() + "\n...[compressed]"
