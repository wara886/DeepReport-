"""Repair existing generated report artifacts from quality gate feedback."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from src.agents.final_answer_agent import (
    _markdown_to_simple_html,
    auto_rewrite_core_sections,
    normalize_report_headings,
    remove_debug_leakage,
    remove_internal_ids,
    remove_template_phrases,
)
from src.evaluation.delivery_gate import build_delivery_gate_from_outputs, write_delivery_gate_for_outputs
from src.evaluation.quality_remediation import build_quality_remediation_plan_from_outputs, write_quality_remediation_plan_for_outputs
from src.evaluation.report_quality import evaluate_report_quality_from_paths, write_quality_outputs_for_paths
from src.evaluation.section_repair import repair_failed_sections_for_outputs
from src.evaluation.section_verification import write_section_verification
from src.data.canonical_metrics import write_canonical_metrics_artifact
from src.report.citation_binder import CitationBinder
from src.report.contract_builder import build_report_section_contracts


def repair_real_report_artifact(
    outputs_dir: str | Path,
    reports_dir: str | Path,
    *,
    run_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Rewrite thin core sections in an existing report and re-run gates.

    This is intentionally deterministic and bounded. It uses the existing
    claims/evidence/metrics artifacts plus quality feedback; it does not invent
    official evidence and does not call an LLM.
    """

    outputs = Path(outputs_dir)
    reports = Path(reports_dir)
    run_root = Path(run_dir) if run_dir is not None else outputs.parent
    report_path = reports / "report.md"
    before_markdown = _read_text(report_path)
    _refresh_real_artifact_contracts(outputs=outputs, reports=reports)
    before_quality = evaluate_report_quality_from_paths(outputs, reports, run_root)
    write_quality_outputs_for_paths(outputs, reports, before_quality)
    before_gate = build_delivery_gate_from_outputs(outputs, run_root)
    write_delivery_gate_for_outputs(outputs, before_gate)
    plan = build_quality_remediation_plan_from_outputs(outputs, run_root)
    write_quality_remediation_plan_for_outputs(outputs, plan)
    before_section_verification = write_section_verification(
        outputs,
        markdown=before_markdown,
        report_section_contracts=_read_json(outputs / "report_section_contracts.json", {}),
        quality_remediation_plan={},
    )

    if not before_markdown.strip():
        return _result(
            outputs=outputs,
            reports=reports,
            before_quality=before_quality,
            before_gate=before_gate,
            after_quality=before_quality,
            after_gate=before_gate,
            plan=plan,
            changed=False,
            reason="missing_report_markdown",
        )

    repaired = auto_rewrite_core_sections(
        normalize_report_headings(before_markdown),
        claims=_read_list(outputs / "claims.json"),
        evidence_records=_read_list(outputs / "evidence.json"),
        financial_metrics=_read_json(outputs / "financial_metrics.json", {}),
        quality_remediation_plan=plan,
        repair_constraints={
            "required_backfill_sections": plan.get("failed_sections", []),
            "source": "real_artifact_quality_remediation",
        },
    )
    repaired = remove_template_phrases(remove_internal_ids(remove_debug_leakage(normalize_report_headings(repaired))))
    repaired = _remove_internal_metric_key_lines(repaired)
    repaired = auto_rewrite_core_sections(
        repaired,
        claims=_read_list(outputs / "claims.json"),
        evidence_records=_read_list(outputs / "evidence.json"),
        financial_metrics=_read_json(outputs / "financial_metrics.json", {}),
        quality_remediation_plan=plan,
        repair_constraints={
            "required_backfill_sections": plan.get("failed_sections", []),
            "source": "real_artifact_quality_remediation_cleanup",
        },
    )
    repaired = _close_unfinished_plain_lines(repaired)
    changed = repaired.strip() != before_markdown.strip()
    if changed:
        reports.mkdir(parents=True, exist_ok=True)
        report_path.write_text(repaired, encoding="utf-8")
        (reports / "report.html").write_text(
            _markdown_to_simple_html(repaired, title=_report_title(outputs, reports)),
            encoding="utf-8",
        )
        _update_report_json(reports / "report.json", repaired)

    section_repair = repair_failed_sections_for_outputs(
        output_dir=outputs,
        report_dir=reports,
        section_verification=before_section_verification,
    )
    changed = changed or bool(section_repair.get("repaired"))

    after_quality = evaluate_report_quality_from_paths(outputs, reports, run_root)
    write_quality_outputs_for_paths(outputs, reports, after_quality)
    after_gate = build_delivery_gate_from_outputs(outputs, run_root)
    write_delivery_gate_for_outputs(outputs, after_gate)
    result = _result(
        outputs=outputs,
        reports=reports,
        before_quality=before_quality,
        before_gate=before_gate,
        after_quality=after_quality,
        after_gate=after_gate,
        plan=plan,
        changed=changed,
        reason="repaired" if changed else "no_change_needed",
    )
    _write_summary(outputs / "real_artifact_remediation.json", result)
    return result


def _result(
    *,
    outputs: Path,
    reports: Path,
    before_quality: dict[str, Any],
    before_gate: dict[str, Any],
    after_quality: dict[str, Any],
    after_gate: dict[str, Any],
    plan: dict[str, Any],
    changed: bool,
    reason: str,
) -> dict[str, Any]:
    return {
        "schema_version": "real_artifact_remediation.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "outputs_dir": str(outputs),
        "reports_dir": str(reports),
        "changed": changed,
        "reason": reason,
        "failed_sections": list(plan.get("failed_sections", [])),
        "before": {
            "delivery_pass": bool(before_gate.get("delivery_pass")),
            "objective_pass": bool(before_quality.get("objective_pass")),
            "total_score": before_quality.get("total_score"),
            "content_depth_blockers": _issue_count(before_quality, "content_depth"),
            "official_evidence_blockers": _issue_count(before_quality, "official_evidence"),
        },
        "after": {
            "delivery_pass": bool(after_gate.get("delivery_pass")),
            "objective_pass": bool(after_quality.get("objective_pass")),
            "total_score": after_quality.get("total_score"),
            "content_depth_blockers": _issue_count(after_quality, "content_depth"),
            "official_evidence_blockers": _issue_count(after_quality, "official_evidence"),
        },
    }


def _refresh_real_artifact_contracts(*, outputs: Path, reports: Path) -> None:
    run_summary = _read_json(outputs / "run_summary.json", {})
    symbol = str(run_summary.get("symbol") or run_summary.get("canonical_symbol") or "")
    period = str(run_summary.get("period") or "")
    financial_metrics = _read_json(outputs / "financial_metrics.json", {})
    tables = _read_json(outputs / "tables.json", [])
    canonical = write_canonical_metrics_artifact(
        outputs,
        financial_metrics=financial_metrics,
        tables=tables,
        symbol=symbol,
        period=period,
    )
    evidence_records = _read_list(outputs / "evidence.json")
    claims = _read_list(outputs / "claims.json")
    section_dossiers = _read_json(outputs / "section_dossiers.json", {})
    analysis_artifacts = {
        "financial_metrics": canonical,
        "raw_financial_metrics": financial_metrics,
        "tables": tables,
        "claims": claims,
        "section_dossiers": section_dossiers,
        "valuation_model": _read_json(outputs / "valuation_model.json", {}),
        "valuation_sensitivity": _read_json(outputs / "valuation_sensitivity.json", {}),
        "peer_analysis": _read_json(outputs / "peer_analysis.json", {}),
        "currency_audit": _read_json(outputs / "currency_audit.json", {}),
        "pdf_section_summaries": _read_json(outputs / "pdf_section_summaries.json", []),
        "pdf_section_chunks": _read_json(outputs / "pdf_section_chunks.json", []),
    }
    state = {
        "symbol": symbol,
        "period": period,
        "claims": claims,
        "analysis_artifacts": analysis_artifacts,
        "section_dossiers": section_dossiers if isinstance(section_dossiers, dict) else {},
        "entity_resolution": _read_json(outputs / "entity_resolution.json", {}),
    }
    contracts = build_report_section_contracts(
        state=state,
        evidence_records=evidence_records,
        analysis_artifacts=analysis_artifacts,
        section_dossiers=section_dossiers if isinstance(section_dossiers, dict) else {},
        citations=_read_list(outputs / "citations.json"),
    )
    binder = CitationBinder(evidence_records)
    binder.bind_all(contracts)
    contracts.to_json_file(str(outputs / "report_section_contracts.json"))
    binder.write_artifacts(str(outputs))


def _issue_count(report: dict[str, Any], category: str) -> int:
    return sum(1 for item in report.get("issues", []) if isinstance(item, dict) and item.get("category") == category)


def _report_title(outputs: Path, reports: Path) -> str:
    report_json = _read_json(reports / "report.json", {})
    if isinstance(report_json, dict) and report_json.get("title"):
        return str(report_json["title"])
    summary = _read_json(outputs / "run_summary.json", {})
    symbol = str(summary.get("symbol") or "研究报告")
    period = str(summary.get("period") or "")
    return f"{symbol} {period} 研究报告".strip()


def _update_report_json(path: Path, markdown: str) -> None:
    payload = _read_json(path, {})
    if not isinstance(payload, dict):
        payload = {}
    payload["markdown"] = markdown
    payload["remediated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_summary(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _read_list(path: Path) -> list[dict[str, Any]]:
    value = _read_json(path, [])
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _remove_internal_metric_key_lines(markdown: str) -> str:
    blocked = ("revenue_growth_pct", "adjusted_net_income", "non_recurring_gain")
    lines = []
    for line in str(markdown or "").splitlines():
        if any(key in line for key in blocked):
            continue
        lines.append(line.rstrip())
    return "\n".join(lines).strip() + "\n"


def _close_unfinished_plain_lines(markdown: str) -> str:
    lines: list[str] = []
    for raw in str(markdown or "").splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "|", "-", "*", "<", ">")):
            lines.append(line)
            continue
        if stripped.endswith(("与", "及", "和", "并", "或", "、", "：", "，", ",")):
            line = line.rstrip("与及和并或、：，,") + "。"
        lines.append(line)
    return "\n".join(lines).strip() + "\n"
