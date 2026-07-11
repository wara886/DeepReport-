"""Section-level deterministic repair for LangGraph report runtime."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict

from src.agents.final_answer_agent import (
    auto_rewrite_core_sections,
    remove_broken_or_half_sentences,
    remove_debug_leakage,
    remove_internal_ids,
    remove_template_phrases,
)
from src.data.canonical_metrics import canonical_metrics_as_financial_metrics
from src.evaluation.section_verification import write_section_verification
from src.report.html_report_generator import render_professional_html_report


SECTION_REPAIR_ALIASES = {
    "risks": "risk",
    "conclusion": "investment_conclusion",
    "business_overview": "business_profile",
}


def repair_failed_sections_for_outputs(
    *,
    output_dir: str | Path,
    report_dir: str | Path,
    section_verification: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Repair failed core sections and re-run deterministic section verification."""

    outputs = Path(output_dir)
    reports = Path(report_dir)
    report_md = reports / "report.md"
    before = section_verification if isinstance(section_verification, dict) else _read_json(outputs / "section_verification.json", {})
    failed_sections = [str(item) for item in before.get("failed_sections") or [] if str(item).strip()]
    failed_sections = _dedupe(failed_sections + _quality_issue_target_sections(outputs))
    before_status = str(before.get("status") or "missing")
    if not failed_sections:
        return {
            "schema_version": "section_repair.v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "not_required",
            "before_status": before_status,
            "after_status": before_status,
            "failed_sections_before": [],
            "failed_sections_after": [],
            "repaired": False,
        }
    if not report_md.exists():
        return {
            "schema_version": "section_repair.v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "skipped_missing_report",
            "before_status": before_status,
            "after_status": before_status,
            "failed_sections_before": failed_sections,
            "failed_sections_after": failed_sections,
            "repaired": False,
        }

    original = report_md.read_text(encoding="utf-8")
    claims = _read_records(outputs / "claims.json")
    evidence = _read_records(outputs / "evidence.json")
    raw_financial_metrics = _read_json(outputs / "financial_metrics.json", {})
    canonical_metrics = _read_json(outputs / "canonical_metrics.json", {})
    financial_metrics = canonical_metrics_as_financial_metrics(canonical_metrics, fallback=raw_financial_metrics)
    contracts = _read_json(outputs / "report_section_contracts.json", {})

    repair_plan = {
        "schema_version": "section_repair_plan.v1",
        "quality_feedback_used": True,
        "failed_sections": _repair_target_sections(failed_sections),
        "required_fixes": _required_fixes(before),
        "forbidden_patterns": [
            "本节暂不展开",
            "暂不展开详细分析",
            "需进一步分析",
            "暂无可验证结论",
            "框架待补",
            "估值分析待补",
            "敏感性分析框架待补",
        ],
        "planner_constraints": [
            "只修复失败章节，不改写已通过章节。",
            "所有数值优先来自 canonical_metrics.json。",
            "无法验证的数据必须说明证据边界，不能写成确定事实。",
        ],
    }
    repaired_md = auto_rewrite_core_sections(
        original,
        claims=claims,
        evidence_records=evidence,
        financial_metrics=financial_metrics,
        quality_remediation_plan=repair_plan,
    )
    repaired_md = remove_broken_or_half_sentences(repaired_md)
    repaired_md = remove_debug_leakage(repaired_md)
    repaired_md = remove_internal_ids(repaired_md)
    repaired_md = remove_template_phrases(repaired_md)
    changed = repaired_md != original
    if changed:
        report_md.write_text(repaired_md, encoding="utf-8")
        _rewrite_report_html_and_json(reports=reports, markdown=repaired_md, output_dir=outputs)

    after = write_section_verification(
        outputs,
        markdown=repaired_md,
        report_section_contracts=contracts,
        quality_remediation_plan={},
    )
    summary = {
        "schema_version": "section_repair.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "repaired" if changed and after.get("status") == "passed" else ("attempted" if changed else "no_change"),
        "before_status": before_status,
        "after_status": after.get("status"),
        "failed_sections_before": failed_sections,
        "failed_sections_after": list(after.get("failed_sections") or []),
        "repaired": changed,
        "report_markdown_chars_before": len(original),
        "report_markdown_chars_after": len(repaired_md),
        "repair_plan": repair_plan,
    }
    path = outputs / "section_repair.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return summary


def _repair_target_sections(failed_sections: list[str]) -> list[str]:
    output: list[str] = []
    for section in failed_sections:
        output.append(section)
        alias = SECTION_REPAIR_ALIASES.get(section)
        if alias:
            output.append(alias)
    return _dedupe(output)


def _required_fixes(section_verification: Dict[str, Any]) -> list[str]:
    issues = section_verification.get("issues") if isinstance(section_verification.get("issues"), list) else []
    fixes = []
    for issue in issues[:10]:
        section = str(issue.get("section") or "")
        message = str(issue.get("message") or issue.get("reason") or "")
        if section or message:
            fixes.append(f"Repair {section or 'section'}: {message}")
    return fixes or ["Rewrite failed core sections to satisfy formal section contract."]


def _quality_issue_target_sections(outputs: Path) -> list[str]:
    targets: list[str] = []
    for filename in ("quality_report.json", "llm_quality_review.json", "delivery_gate.json"):
        payload = _read_json(outputs / filename, {})
        issues = payload.get("issues") if isinstance(payload, dict) else []
        if not isinstance(issues, list):
            continue
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            text = " ".join(
                str(issue.get(key) or "")
                for key in ("category", "message", "detail", "description", "section")
            ).lower()
            if any(token in text for token in ("investment conclusion", "投资结论", "投资建议", "评级", "recommendation")):
                targets.append("investment_conclusion")
            if any(token in text for token in ("peer", "同行", "可比")):
                targets.append("peer_compare")
            if any(token in text for token in ("valuation sensitivity", "敏感性")):
                targets.append("valuation_sensitivity")
    return _dedupe(targets)


def _rewrite_report_html_and_json(*, reports: Path, markdown: str, output_dir: Path) -> None:
    title = _report_title(markdown)
    charts = _read_records(output_dir / "charts.json")
    citations = _read_records(output_dir / "citations.json")
    html = render_professional_html_report(markdown, title=title, charts=charts, citations=citations)
    (reports / "report.html").write_text(html, encoding="utf-8")
    report_json_path = reports / "report.json"
    report_json = _read_json(report_json_path, {})
    if isinstance(report_json, dict):
        report_json.setdefault("title", title)
        report_json["markdown"] = markdown
        report_json["section_repair_applied"] = True
        report_json_path.write_text(json.dumps(report_json, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _report_title(markdown: str) -> str:
    for line in str(markdown or "").splitlines():
        if line.startswith("# "):
            return line[2:].strip() or "财务研究报告"
    return "财务研究报告"


def _read_records(path: Path) -> list[dict[str, Any]]:
    payload = _read_json(path, [])
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("items", "records", "evidence", "claims", "charts", "citations"):
            value = payload.get(key)
            if isinstance(value, list):
                return [dict(item) for item in value if isinstance(item, dict)]
    return []


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            output.append(item)
    return output
