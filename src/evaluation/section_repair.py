"""Section-level deterministic repair for LangGraph report runtime."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from collections.abc import Callable
from typing import Any, Dict

from src.agents.final_answer_agent import (
    auto_rewrite_core_sections,
    enforce_contract_numeric_consistency,
    remove_broken_or_half_sentences,
    remove_debug_leakage,
    remove_internal_ids,
    remove_template_phrases,
)
from src.data.canonical_metrics import canonical_metrics_as_financial_metrics
from src.evaluation.section_verification import build_section_verification, write_section_verification
from src.report.html_report_generator import render_professional_html_report


SECTION_REPAIR_ALIASES = {
    "risks": "risk",
    "conclusion": "investment_conclusion",
    "business_overview": "business_profile",
}

PACK_SECTION_KEYS = {
    "risk": "risks",
    "business_profile": "business_overview",
    "investment_conclusion": "conclusion",
}

CONTRACT_SECTION_KEYS = {
    "risk": "risk_factors",
    "risks": "risk_factors",
    "business_profile": "business_overview",
    "investment_conclusion": "conclusion",
}


def repair_failed_sections_for_outputs(
    *,
    output_dir: str | Path,
    report_dir: str | Path,
    section_verification: Dict[str, Any] | None = None,
    repair_callback: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
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
    evidence_packs = _read_json(outputs / "section_evidence_packs.json", {})

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
    targets = set(_repair_target_sections(failed_sections))
    attempts: list[dict[str, Any]] = []
    repaired_md = original
    if repair_callback is not None:
        repaired_md, attempts = _apply_callback_repairs(
            repaired_md,
            targets=targets,
            callback=repair_callback,
            contracts=contracts,
            evidence_packs=evidence_packs,
            verification=before,
        )
    callback_changed = repaired_md != original
    if not callback_changed:
        candidate = auto_rewrite_core_sections(
            original,
            claims=claims,
            evidence_records=evidence,
            financial_metrics=financial_metrics,
            quality_remediation_plan=repair_plan,
        )
        repaired_md = _restore_non_target_sections(original, candidate, targets)
        attempts.append({
            "strategy": "deterministic_section_rewrite",
            "status": "changed" if repaired_md != original else "no_change",
            "target_sections": sorted(targets),
        })
    repaired_md = remove_broken_or_half_sentences(repaired_md)
    repaired_md = remove_debug_leakage(repaired_md)
    repaired_md = remove_internal_ids(repaired_md)
    repaired_md = remove_template_phrases(repaired_md)
    repaired_md = enforce_contract_numeric_consistency(repaired_md, contracts)
    changed = repaired_md != original
    if changed:
        report_md.write_text(repaired_md, encoding="utf-8")
        _rewrite_report_html_and_json(reports=reports, markdown=repaired_md, output_dir=outputs)

    after = write_section_verification(
        outputs,
        markdown=repaired_md,
        report_section_contracts=contracts,
        quality_remediation_plan={},
        section_evidence_packs=evidence_packs,
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
        "repair_strategy": "llm_section_rewrite" if callback_changed else "deterministic_section_rewrite",
        "model_status": "used" if callback_changed else ("failed_or_no_change" if repair_callback else "unavailable"),
        "attempts": attempts,
        "evidence_ids_consumed": _consumed_evidence_ids(after, targets),
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


SECTION_TITLES = {
    "executive_summary": "执行摘要",
    "business_overview": "业务概览",
    "business_profile": "业务概览",
    "financial_analysis": "财务分析",
    "valuation": "估值观察",
    "risks": "风险评估",
    "risk": "风险评估",
    "conclusion": "投资结论",
    "investment_conclusion": "投资结论",
}


def _apply_callback_repairs(
    markdown: str,
    *,
    targets: set[str],
    callback: Callable[[dict[str, Any]], dict[str, Any]],
    contracts: dict[str, Any],
    evidence_packs: dict[str, Any],
    verification: dict[str, Any],
) -> tuple[str, list[dict[str, Any]]]:
    output = markdown
    attempts: list[dict[str, Any]] = []
    processed_titles: set[str] = set()
    contract_map = contracts.get("contracts") if isinstance(contracts.get("contracts"), dict) else {}
    pack_map = evidence_packs.get("packs") if isinstance(evidence_packs.get("packs"), dict) else {}
    results = verification.get("section_results") if isinstance(verification.get("section_results"), dict) else {}
    for section in sorted(targets):
        title = SECTION_TITLES.get(section)
        if not title or title in processed_titles or _section_body(output, title) is None:
            continue
        processed_titles.add(title)
        pack_key = PACK_SECTION_KEYS.get(section, section)
        contract_key = CONTRACT_SECTION_KEYS.get(section, section)
        evidence_pack = pack_map.get(pack_key) if isinstance(pack_map.get(pack_key), dict) else {}
        payload = {
            "section_key": section,
            "title": title,
            "original_section": _section_body(output, title),
            "contract": contract_map.get(contract_key) or {},
            "evidence_pack": evidence_pack,
            "verification": results.get(pack_key) or results.get(section) or {},
        }
        for attempt_number in range(1, 3):
            payload["attempt_number"] = attempt_number
            payload["original_section"] = _section_body(output, title)
            try:
                response = callback(payload)
                body = str(response.get("section_markdown") or response.get("body") or "").strip() if isinstance(response, dict) else ""
                if not body:
                    attempts.append({
                        "section": section,
                        "attempt_number": attempt_number,
                        "strategy": "llm_section_rewrite",
                        "status": "empty_response",
                    })
                    continue
                body = _ensure_must_use_citation(body, evidence_pack)
                candidate = _replace_section_body(output, title, body)
                immediate = build_section_verification(
                    markdown=candidate,
                    report_section_contracts=contracts,
                    quality_remediation_plan={},
                    section_evidence_packs=evidence_packs,
                )
                section_result = _verification_result(immediate, pack_key, section)
                output = candidate
                attempt = {
                    "section": section,
                    "attempt_number": attempt_number,
                    "strategy": "llm_section_rewrite",
                    "status": "passed" if section_result.get("status") == "passed" else "contract_failed",
                    "verification_reasons": list(section_result.get("reasons") or []),
                    "missing_citation_evidence_ids": list(section_result.get("missing_citation_evidence_ids") or []),
                }
                if response.get("llm_run_id"):
                    attempt["llm_run_id"] = str(response["llm_run_id"])
                attempts.append(attempt)
                if section_result.get("status") == "passed":
                    break
                payload["verification"] = section_result
            except Exception as exc:
                attempts.append({
                    "section": section,
                    "attempt_number": attempt_number,
                    "strategy": "llm_section_rewrite",
                    "status": "failed",
                    "failure_reason": str(exc),
                })
    return output, attempts


def _verification_result(verification: dict[str, Any], pack_key: str, section: str) -> dict[str, Any]:
    results = verification.get("section_results") if isinstance(verification.get("section_results"), dict) else {}
    row = results.get(pack_key) or results.get(section)
    return row if isinstance(row, dict) else {"status": "failed", "reasons": ["section_verification_missing"]}


def _ensure_must_use_citation(body: str, evidence_pack: dict[str, Any]) -> str:
    must_use = [str(item) for item in evidence_pack.get("must_use_evidence_ids") or [] if str(item)]
    if not must_use:
        return body
    rows = evidence_pack.get("must_use_evidence") if isinstance(evidence_pack.get("must_use_evidence"), list) else []
    labels = [
        str(label)
        for row in rows
        if isinstance(row, dict) and str(row.get("evidence_id") or "") in must_use
        for label in row.get("citation_labels") or []
        if str(label)
    ]
    if any(f"[{evidence_id}]" in body or f"【{evidence_id}】" in body for evidence_id in must_use):
        return body
    if any(f"[{label}]" in body or f"【{label}】" in body for label in labels):
        return body
    return body.rstrip() + f" [{must_use[0]}]"


def _restore_non_target_sections(original: str, candidate: str, targets: set[str]) -> str:
    output = candidate
    target_titles = {SECTION_TITLES[key] for key in targets if key in SECTION_TITLES}
    for title in set(SECTION_TITLES.values()) - target_titles:
        body = _section_body(original, title)
        if body is not None and _section_body(output, title) is not None:
            output = _replace_section_body(output, title, body)
    return output


def _section_body(markdown: str, title: str) -> str | None:
    import re
    match = re.search(rf"^##\s+{re.escape(title)}\s*$", markdown, re.MULTILINE)
    if not match:
        return None
    start = match.end()
    next_heading = re.search(r"^##\s+", markdown[start:], re.MULTILINE)
    end = start + next_heading.start() if next_heading else len(markdown)
    return markdown[start:end].strip()


def _replace_section_body(markdown: str, title: str, body: str) -> str:
    import re
    match = re.search(rf"^##\s+{re.escape(title)}\s*$", markdown, re.MULTILINE)
    if not match:
        return markdown
    start = match.end()
    next_heading = re.search(r"^##\s+", markdown[start:], re.MULTILINE)
    end = start + next_heading.start() if next_heading else len(markdown)
    suffix = markdown[end:]
    separator = "\n\n" if suffix else "\n"
    return markdown[:start] + "\n" + body.strip() + separator + suffix.lstrip("\n")


def _consumed_evidence_ids(verification: dict[str, Any], targets: set[str]) -> list[str]:
    results = verification.get("section_results") if isinstance(verification.get("section_results"), dict) else {}
    values = []
    for section in targets:
        row = results.get(section) if isinstance(results.get(section), dict) else {}
        values.extend(_dedupe([str(item) for item in row.get("consumed_evidence_ids") or []]))
    return _dedupe(values)
