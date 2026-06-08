"""LLM-assisted verifier agent."""

from __future__ import annotations

from typing import Any, Dict, List

from src.agents.base_agent import AgentTask, BaseAgent, TaskResult
from src.agents.context_packer import build_revision_brief, pack_claims, pack_evidence_records, pack_markdown_excerpt
from src.agents.evidence_gap import build_evidence_gaps
from src.agents.verifier import Verifier
from src.models import ModelAdapter
from src.schemas.claim import ClaimItem


VERIFIER_SYSTEM_PROMPT = """You are VerifierAgent in a financial multi-agent research system.
Check whether report claims are supported by provided evidence ids and whether citations are present.
Return only valid JSON:
{"passed":true,"errors":[],"warnings":[],"fix_recommendations":["..."]}
Be strict about unsupported numbers, but do not require external browsing.
"""


class VerifierAgent(BaseAgent):
    """Verify report completeness, claim support, and citation coverage."""

    def __init__(self, model: ModelAdapter | None = None, tools: Dict[str, Any] | None = None):
        super().__init__(name="VerifierAgent", model=model, tools=tools)
        self.rule_verifier = Verifier()

    def get_capabilities(self) -> List[str]:
        return [
            "verify claim support and citation coverage",
            "check required report sections",
            "produce fix recommendations for weak claims",
        ]

    def execute_task(self, task: AgentTask) -> TaskResult:
        claims = _claim_items(task.parameters.get("claims", []))
        markdown = str(task.parameters.get("markdown", ""))
        evidence_records = task.parameters.get("evidence_records", [])
        charts = task.parameters.get("charts", [])
        tables = task.parameters.get("tables", [])
        valuation = task.parameters.get("valuation", {})
        conversation_brief = str(task.parameters.get("conversation_brief", "")).strip()
        skill_brief = str(task.parameters.get("skill_brief", "")).strip()
        expected_symbol = str(task.parameters.get("expected_symbol", "")).strip().upper()
        entity_resolution = task.parameters.get("entity_resolution", {})
        rule_report = self.rule_verifier.verify(
            claims=claims,
            markdown=markdown,
            evidence_records=evidence_records if isinstance(evidence_records, list) else [],
            charts=charts if isinstance(charts, list) else [],
            tables=tables if isinstance(tables, list) else [],
            valuation=valuation if isinstance(valuation, dict) else {},
            expected_symbol=expected_symbol,
        )
        report: Dict[str, Any] = dict(rule_report)
        report["llm_used"] = False
        if isinstance(entity_resolution, dict):
            report["entity_resolution"] = entity_resolution
        packed_claims, claim_pack_meta = pack_claims([item.to_dict() for item in claims], max_items=16, text_limit=280, total_chars=2600)
        prioritized_ids = []
        for claim in claims:
            prioritized_ids.extend(claim.evidence_ids)
        packed_evidence, evidence_pack_meta = pack_evidence_records(
            evidence_records if isinstance(evidence_records, list) else [],
            prioritized_evidence_ids=prioritized_ids,
            max_items=16,
            content_limit=500,
            total_chars=5200,
        )
        all_evidence_ids = [
            str(item.get("evidence_id") or item.get("sample_id") or "")
            for item in evidence_records
            if isinstance(item, dict) and str(item.get("evidence_id") or item.get("sample_id") or "").strip()
        ]
        for claim in claims:
            for evidence_id in claim.evidence_ids:
                eid = str(evidence_id or "").strip()
                if eid and eid not in all_evidence_ids:
                    all_evidence_ids.append(eid)
        report["context_pack_meta"] = {
            "claims": claim_pack_meta,
            "evidence": evidence_pack_meta,
        }

        if self.model:
            try:
                payload = self.model.generate_json(
                    prompt=_build_verifier_prompt(
                        rule_report=rule_report,
                        claims=packed_claims,
                        markdown=pack_markdown_excerpt(markdown, max_chars=2200),
                        evidence_records=packed_evidence,
                        available_evidence_ids=all_evidence_ids,
                        conversation_brief=conversation_brief,
                        skill_brief=skill_brief,
                    ),
                    system_prompt=VERIFIER_SYSTEM_PROMPT,
                )
                report.update(
                    {
                        "llm_used": True,
                        "llm_passed": bool(payload.get("passed", False)),
                        "llm_errors": payload.get("errors", []) if isinstance(payload.get("errors"), list) else [],
                        "llm_warnings": payload.get("warnings", []) if isinstance(payload.get("warnings"), list) else [],
                        "fix_recommendations": payload.get("fix_recommendations", [])
                        if isinstance(payload.get("fix_recommendations"), list)
                        else [],
                    }
                )
                report = _apply_llm_verifier_overrides(report)
                report["passed"] = bool(report.get("passed", False)) and bool(payload.get("passed", False))
                if report.get("llm_override_passed") is True:
                    report["passed"] = bool(rule_report.get("passed", False))
            except Exception as exc:
                report["llm_error"] = str(exc)
        report["rework_required"] = not bool(report.get("passed", False))
        if report["rework_required"] and not report.get("fix_recommendations"):
            report["fix_recommendations"] = ["Revise unsupported numbers, missing citations, and section coverage before finalizing."]
        report["evidence_gaps"] = build_evidence_gaps(
            verification_report=report,
            claims=[item.to_dict() for item in claims],
            expected_symbol=expected_symbol,
            period=str(task.parameters.get("period", "")),
        )
        report["revision_brief"] = build_revision_brief(report)

        return self.success(task, {"verification_report": report})


def _claim_items(raw: Any) -> List[ClaimItem]:
    if not isinstance(raw, list):
        return []
    claims: List[ClaimItem] = []
    for item in raw:
        if isinstance(item, ClaimItem):
            claims.append(item)
        elif isinstance(item, dict):
            claims.append(ClaimItem.from_dict(item))
    return claims


def _build_verifier_prompt(
    rule_report: Dict[str, Any],
    claims: List[Dict[str, Any]],
    markdown: str,
    evidence_records: List[Dict[str, Any]],
    available_evidence_ids: List[str] | None = None,
    conversation_brief: str = "",
    skill_brief: str = "",
) -> str:
    evidence_ids = available_evidence_ids or [str(item.get("evidence_id", "")) for item in evidence_records[:30] if isinstance(item, dict)]
    memory_line = f"Conversation memory:\n{conversation_brief}\n" if conversation_brief else ""
    skill_line = f"Relevant skill brief:\n{skill_brief}\n" if skill_brief else ""
    return (
        f"{memory_line}"
        f"{skill_line}"
        f"Rule verifier report: {rule_report}\n"
        f"Available evidence ids: {evidence_ids}\n"
        "Markdown may use numbered citations like [1], [2]; treat them as valid when the reference list maps them "
        "to evidence records or when the corresponding claim evidence_id is present above.\n"
        f"Claims: {claims[:20]}\n"
        f"Evidence records: {evidence_records[:16]}\n"
        f"Markdown report excerpt: {markdown[:4000]}"
    )


def _apply_llm_verifier_overrides(report: Dict[str, Any]) -> Dict[str, Any]:
    """Downgrade LLM objections that contradict deterministic artifact audits."""

    valuation_audit = report.get("valuation_audit") if isinstance(report.get("valuation_audit"), dict) else {}
    valuation_ok = bool(valuation_audit.get("passed", False))
    raw_errors = [str(item) for item in report.get("llm_errors", []) if str(item).strip()]
    raw_warnings = [str(item) for item in report.get("llm_warnings", []) if str(item).strip()]
    if not valuation_ok or not raw_errors:
        report["llm_errors"] = raw_errors
        report["llm_warnings"] = raw_warnings
        return report

    kept_errors: List[str] = []
    downgraded: List[str] = []
    for item in raw_errors:
        if _is_valuation_artifact_objection(item):
            downgraded.append(item)
        else:
            kept_errors.append(item)
    if downgraded:
        raw_warnings.extend([f"LLM valuation objection downgraded because valuation_audit passed: {item}" for item in downgraded])
        report["llm_override_passed"] = not kept_errors
        report["llm_override_reason"] = "valuation_audit_passed_for_derived_model_outputs"
    report["llm_errors"] = kept_errors
    report["llm_warnings"] = raw_warnings
    if not kept_errors and report.get("llm_passed") is False and downgraded:
        report["llm_passed"] = True
    return report


def _is_valuation_artifact_objection(text: str) -> bool:
    lowered = str(text or "").lower()
    valuation_terms = (
        "valuation",
        "target price",
        "equity value",
        "\u4f30\u503c",
        "\u76ee\u6807\u4ef7",
        "\u80a1\u6743\u4ef7\u503c",
    )
    evidence_terms = (
        "evidence",
        "support",
        "citation",
        "\u8bc1\u636e",
        "\u652f\u6301",
        "\u7f3a\u4e4f",
        "\u7f3a\u5c11",
    )
    return any(term in lowered for term in valuation_terms) and any(term in lowered for term in evidence_terms)
