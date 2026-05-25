"""Artifact-derived metrics for the phased company-report benchmark.

Phase 1 deliberately reads existing run artifacts only. It does not invoke
agents, rewrite reports, or claim formal baseline-comparison results.
"""

from __future__ import annotations

from collections import Counter
import csv
import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List

from src.data.company_universe import canonicalize_symbol, infer_market_from_symbol
from src.evaluation.report_quality import evaluate_report_quality_from_paths


ARTIFACT_DERIVED_TRACE_LABEL = "Traceable Claim Rate (artifact-derived)"
BASIC_ARTIFACTS = ("claims.json", "evidence.json", "citations.json", "verification_report.json")
DELIVERY_REQUIRED_CHECKS = (
    "identity_resolved",
    "non_empty_executive_summary",
    "non_empty_risk",
    "non_empty_investment_conclusion",
    "citations_in_body",
    "three_statements_or_disclosed_gap",
    "valuation_or_reason",
    "chart_no_serious_conflict",
)
FAILURE_CATEGORIES = (
    "identity_resolution",
    "source_access_or_fetch",
    "filing_or_pdf_parsing",
    "three_statement_coverage",
    "valuation_input_missing",
    "citation_or_evidence_gap",
    "chart_text_mismatch",
    "quality_gate_blocker",
    "runtime_or_model_failure",
)
CRITICAL_SECTION_MARKERS = (
    "financial",
    "statement",
    "three_statement",
    "peer",
    "valuation",
    "risk",
    "conclusion",
    "investment",
    "财务",
    "三表",
    "同行",
    "估值",
    "风险",
    "投资",
    "结论",
)


def canonical_symbol(value: str) -> str:
    """Normalize a recorded ticker for case matching."""

    text = str(value or "").upper().strip()
    market = infer_market_from_symbol(text).get("market", "")
    return canonicalize_symbol(text, market=market)


def locate_report_dir(outputs_dir: str | Path) -> Path:
    """Locate reports for both nested eval outputs and split data/report layouts."""

    outputs = Path(outputs_dir)
    candidates = [outputs.parent / "reports"]
    parts = list(outputs.parts)
    if "outputs" in parts:
        index = parts.index("outputs")
        replaced = parts[:index] + ["reports"] + parts[index + 1 :]
        candidates.append(Path(*replaced).parent / "reports")
    if outputs.name == "outputs" and outputs.parent.name == "company":
        candidates.insert(0, outputs.parent.parent / "company" / "reports")
    for candidate in candidates:
        if (candidate / "report.md").exists():
            return candidate
    return candidates[0]


def basic_artifact_gaps(outputs_dir: str | Path, reports_dir: str | Path | None = None) -> List[str]:
    """Return artifacts required before an existing run can enter metric denominators."""

    outputs = Path(outputs_dir)
    reports = Path(reports_dir) if reports_dir is not None else locate_report_dir(outputs)
    missing = [name for name in BASIC_ARTIFACTS if not (outputs / name).exists()]
    if not (reports / "report.md").exists():
        missing.append("report.md")
    return missing


def evaluate_existing_run(
    outputs_dir: str | Path,
    case: Dict[str, Any],
    reports_dir: str | Path | None = None,
) -> Dict[str, Any]:
    """Compute Phase 1 metrics from one existing run without writing artifacts."""

    outputs = Path(outputs_dir)
    reports = Path(reports_dir) if reports_dir is not None else locate_report_dir(outputs)
    missing = basic_artifact_gaps(outputs, reports)
    base = {
        "case_id": str(case.get("case_id", "")),
        "market": str(case.get("market", "")),
        "company_name": str(case.get("company_name", "")),
        "canonical_symbol": str(case.get("canonical_symbol", "")),
        "outputs_dir": str(outputs),
        "reports_dir": str(reports),
        "metric_scope": "artifact_derived_v0",
    }
    if missing:
        return {
            **base,
            "status": "not_evaluable",
            "not_evaluable_reason": "missing required artifacts: " + ", ".join(missing),
            "missing_artifacts": missing,
            "delivery_pass": False,
            "objective_quality_score": None,
            "traceable_claim_rate": None,
            "failure_categories": ["runtime_or_model_failure"],
        }

    summary = _read_dict(outputs / "run_summary.json")
    claims = _read_list(outputs / "claims.json")
    evidence = _read_list(outputs / "evidence.json")
    citations = _read_list(outputs / "citations.json")
    verification = _read_dict(outputs / "verification_report.json")
    report_text = (reports / "report.md").read_text(encoding="utf-8")
    quality, quality_source = _quality_payload(outputs, reports)
    chart_consistency = _read_dict(outputs / "chart_consistency.json") or _read_dict(outputs / "multimodal_consistency.json")
    financial_metrics = _read_dict(outputs / "financial_metrics.json")
    numeric_audit = _read_dict(outputs / "numeric_audit.json") or _read_dict(outputs / "numeric_audit_v1.json")
    traceability = traceable_claim_metrics(
        claims=claims,
        evidence=evidence,
        citations=citations,
        report_text=report_text,
        financial_metrics=financial_metrics,
        numeric_audit=numeric_audit,
    )
    checks = deterministic_delivery_checks(
        case=case,
        summary=summary,
        report_text=report_text,
        citations=citations,
        quality=quality,
        verification=verification,
        chart_consistency=chart_consistency,
        traceability=traceability,
    )
    categories = failure_categories(checks=checks, quality=quality, verification=verification)
    total_score = _safe_float(quality.get("total_score"))
    historic_gate = _read_dict(outputs / "delivery_gate.json")
    return {
        **base,
        "status": "evaluated",
        "symbol": str(summary.get("symbol") or ""),
        "period": str(summary.get("period") or ""),
        "run_model": str(summary.get("model") or ""),
        "delivery_pass": all(checks.get(key, False) for key in DELIVERY_REQUIRED_CHECKS),
        "delivery_checks": checks,
        "delivery_required_checks": list(DELIVERY_REQUIRED_CHECKS),
        "delivery_failed_checks": [key for key in DELIVERY_REQUIRED_CHECKS if not checks.get(key, False)],
        "objective_quality_score": round(total_score * 100, 2) if total_score is not None else None,
        "objective_quality_source": quality_source,
        "traceable_claim_rate": traceability["rate"],
        "critical_claim_count": traceability["critical_claim_count"],
        "traceable_claim_count": traceability["traceable_claim_count"],
        "traceability_issues": traceability["issues"],
        "failure_categories": categories,
        "existing_three_layer_delivery_pass": historic_gate.get("delivery_pass"),
        "existing_llm_review_pass": historic_gate.get("llm_review_pass"),
    }


def deterministic_delivery_checks(
    case: Dict[str, Any],
    summary: Dict[str, Any],
    report_text: str,
    citations: List[Dict[str, Any]],
    quality: Dict[str, Any],
    verification: Dict[str, Any],
    chart_consistency: Dict[str, Any],
    traceability: Dict[str, Any],
) -> Dict[str, bool]:
    """Build a reproducible delivery gate that does not depend on LLM review."""

    required = quality.get("required_checks", {}) if isinstance(quality.get("required_checks"), dict) else {}
    details = required.get("details", {}) if isinstance(required.get("details"), dict) else {}
    expected_symbol = canonical_symbol(str(case.get("canonical_symbol", "")))
    resolved_symbol = _resolved_symbol(summary)
    issue_counts = quality.get("issue_counts", {}) if isinstance(quality.get("issue_counts"), dict) else {}
    chart_passed = chart_consistency.get("passed") if chart_consistency else True
    has_body_citation = any(_citation_used(item, report_text) for item in citations)
    return {
        "identity_resolved": bool(resolved_symbol and (not expected_symbol or resolved_symbol == expected_symbol)),
        "non_empty_executive_summary": bool(details.get("non_empty_executive_summary", _has_section(report_text, ("执行摘要", "摘要", "Executive Summary")))),
        "non_empty_risk": bool(details.get("non_empty_risk", _has_section(report_text, ("风险", "Risk")))),
        "non_empty_investment_conclusion": bool(details.get("non_empty_investment_conclusion", _has_section(report_text, ("投资结论", "投资建议", "Conclusion")))),
        "citations_in_body": has_body_citation,
        "three_statements_or_disclosed_gap": bool(
            details.get("has_three_table_summary", False) or _has_three_statements_or_disclosed_gap(report_text)
        ),
        "valuation_or_reason": bool(details.get("valuation_or_reason", _has_valuation_or_unavailable_reason(report_text))),
        "chart_no_serious_conflict": chart_passed is not False,
        "verifier_passed": bool(verification.get("passed", False)),
        "critical_claims_traceable": bool(
            traceability.get("critical_claim_count", 0) > 0
            and traceability.get("critical_claim_count") == traceability.get("traceable_claim_count")
        ),
        "no_objective_fatal_or_blocker": int(issue_counts.get("fatal", 0) or 0) == 0
        and int(issue_counts.get("blocker", 0) or 0) == 0,
    }


def traceable_claim_metrics(
    claims: List[Dict[str, Any]],
    evidence: List[Dict[str, Any]],
    citations: List[Dict[str, Any]],
    report_text: str,
    financial_metrics: Dict[str, Any] | None = None,
    numeric_audit: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Compute an initial traceability metric from legacy sidecar artifacts."""

    evidence_ids = {
        str(item.get("evidence_id") or item.get("sample_id") or "")
        for item in evidence
        if str(item.get("evidence_id") or item.get("sample_id") or "")
    }
    critical = [claim for claim in claims if _is_critical_claim(claim)]
    lineage_ids = _metric_lineage_ids(financial_metrics or {})
    traced: List[str] = []
    issues: List[Dict[str, str]] = []
    for index, claim in enumerate(critical, start=1):
        claim_id = str(claim.get("claim_id") or f"claim_{index:04d}")
        claim_evidence = [str(item) for item in claim.get("evidence_ids", []) if str(item)]
        valid_ids = [item for item in claim_evidence if item in evidence_ids]
        used_ids = [
            evidence_id
            for evidence_id in valid_ids
            if _has_used_citation(claim_id, evidence_id, citations, report_text)
        ]
        numeric_ok = _numeric_lineage_ok(claim, lineage_ids=lineage_ids, numeric_audit=numeric_audit or {})
        if valid_ids and used_ids and numeric_ok:
            traced.append(claim_id)
            continue
        reason_parts = []
        if not valid_ids:
            reason_parts.append("missing_valid_evidence")
        if valid_ids and not used_ids:
            reason_parts.append("citation_not_used_in_report")
        if not numeric_ok:
            reason_parts.append("numeric_lineage_missing")
        issues.append({"claim_id": claim_id, "reason": ",".join(reason_parts) or "not_traceable"})
    count = len(critical)
    traced_count = len(traced)
    if not count:
        issues.append({"claim_id": "", "reason": "no_critical_claim_candidates"})
    return {
        "label": ARTIFACT_DERIVED_TRACE_LABEL,
        "critical_claim_count": count,
        "traceable_claim_count": traced_count,
        "rate": round(traced_count / count, 4) if count else 0.0,
        "traceable_claim_ids": traced,
        "issues": issues,
    }


def failure_categories(
    checks: Dict[str, bool],
    quality: Dict[str, Any] | None = None,
    verification: Dict[str, Any] | None = None,
) -> List[str]:
    """Map deterministic failures and existing diagnostics to stable categories."""

    categories: List[str] = []
    if not checks.get("identity_resolved", True):
        categories.append("identity_resolution")
    if not checks.get("three_statements_or_disclosed_gap", True):
        categories.append("three_statement_coverage")
    if not checks.get("valuation_or_reason", True):
        categories.append("valuation_input_missing")
    if not checks.get("citations_in_body", True) or not checks.get("critical_claims_traceable", True):
        categories.append("citation_or_evidence_gap")
    if not checks.get("chart_no_serious_conflict", True):
        categories.append("chart_text_mismatch")
    if not checks.get("no_objective_fatal_or_blocker", True) or not checks.get("verifier_passed", True):
        categories.append("quality_gate_blocker")
    diagnostic_text = _diagnostic_text(quality or {}, verification or {})
    if any(
        term in diagnostic_text
        for term in ("missing_primary_evidence", "no primary evidence source", "missing evidence", "证据缺口", "缺少一手")
    ):
        categories.append("citation_or_evidence_gap")
    if any(
        term in diagnostic_text
        for term in ("pdf parsing", "pdf extraction", "filing parsing", "公告解析失败", "公告提取失败")
    ):
        categories.append("filing_or_pdf_parsing")
    if any(term in diagnostic_text for term in ("source_access", "fetch failed", "数据源失败", "missing_api_key")):
        categories.append("source_access_or_fetch")
    return [item for item in FAILURE_CATEGORIES if item in set(categories)]


def _diagnostic_text(quality: Dict[str, Any], verification: Dict[str, Any]) -> str:
    diagnostics: List[Any] = []
    for payload, keys in ((quality, ("issues", "top_issues")), (verification, ("errors", "warnings", "evidence_gaps"))):
        for key in keys:
            values = payload.get(key, [])
            if isinstance(values, list):
                diagnostics.extend(values)
    return json.dumps(diagnostics, ensure_ascii=False).lower()


def summarize_records(records: List[Dict[str, Any]], total_case_count: int) -> Dict[str, Any]:
    """Aggregate evaluated historical runs; not-run and not-evaluable rows stay visible."""

    observed = [row for row in records if row.get("status") != "not_run"]
    evaluated = [row for row in records if row.get("status") == "evaluated"]
    markets = ["US", "HK", "CN-A"]
    metrics = {market: _metric_summary([row for row in evaluated if row.get("market") == market]) for market in markets}
    failures: Counter[str] = Counter()
    for row in evaluated:
        failures.update(str(value) for value in row.get("failure_categories", []))
    return {
        "schema_version": "benchmark_existing_artifacts.v1",
        "metric_scope": "artifact_derived_v0",
        "total_case_count": total_case_count,
        "observed_run_count": len(observed),
        "evaluable_run_count": len(evaluated),
        "not_run_count": sum(1 for row in records if row.get("status") == "not_run"),
        "not_evaluable_count": sum(1 for row in records if row.get("status") == "not_evaluable"),
        "overall": _metric_summary(evaluated),
        "by_market": metrics,
        "failure_counts": dict(failures),
    }


def write_benchmark_outputs(
    output_dir: str | Path,
    records: List[Dict[str, Any]],
    summary: Dict[str, Any],
) -> Dict[str, str]:
    """Write Phase 1 CSV/Markdown/JSONL report artifacts."""

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary_path = out / "benchmark_summary.csv"
    report_path = out / "benchmark_report.md"
    runs_path = out / "benchmark_runs.jsonl"
    failures_path = out / "benchmark_failures.csv"

    with summary_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["metric", "overall", "US", "HK", "CN-A"])
        writer.writeheader()
        for key, label in [
            ("delivery_pass_rate", "Delivery Pass Rate"),
            ("objective_quality_score", "Objective Quality Score"),
            ("traceable_claim_rate", ARTIFACT_DERIVED_TRACE_LABEL),
        ]:
            writer.writerow(
                {
                    "metric": label,
                    "overall": summary["overall"].get(key),
                    "US": summary["by_market"]["US"].get(key),
                    "HK": summary["by_market"]["HK"].get(key),
                    "CN-A": summary["by_market"]["CN-A"].get(key),
                }
            )
    runs_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in records) + ("\n" if records else ""),
        encoding="utf-8",
    )
    with failures_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["case_id", "market", "canonical_symbol", "status", "category", "detail", "outputs_dir"],
        )
        writer.writeheader()
        for row in records:
            categories = list(row.get("failure_categories", []))
            if row.get("status") == "not_run":
                categories = ["not_run"]
            elif row.get("status") == "not_evaluable" and not categories:
                categories = ["runtime_or_model_failure"]
            for category in categories:
                writer.writerow(
                    {
                        "case_id": row.get("case_id", ""),
                        "market": row.get("market", ""),
                        "canonical_symbol": row.get("canonical_symbol", ""),
                        "status": row.get("status", ""),
                        "category": category,
                        "detail": row.get("not_evaluable_reason", ""),
                        "outputs_dir": row.get("outputs_dir", ""),
                    }
                )
    report_path.write_text(render_benchmark_report(records, summary), encoding="utf-8")
    return {
        "benchmark_summary": str(summary_path),
        "benchmark_report": str(report_path),
        "benchmark_runs": str(runs_path),
        "benchmark_failures": str(failures_path),
    }


def render_benchmark_report(records: List[Dict[str, Any]], summary: Dict[str, Any]) -> str:
    """Render the human-facing Phase 1 report."""

    lines = [
        "# Existing Artifact Benchmark Report",
        "",
        "## Scope",
        "",
        "- Phase: `Existing Artifact Evaluator`.",
        "- This report only summarizes existing multi-agent artifacts; it is not a completed quick-9 rerun or a baseline comparison.",
        f"- observed_runs={summary['observed_run_count']}/{summary['total_case_count']}; evaluable_runs={summary['evaluable_run_count']}.",
        "- Core metric denominators include evaluated runs only; `not_run` and `not_evaluable` rows are shown as coverage gaps and excluded from metric averages.",
        "- `Delivery Pass Rate` uses eight deterministic delivery checks only: identity, summary, risk, conclusion, body citation, three statements or disclosed gap, valuation or reason, and chart consistency.",
        "- Objective quality blockers and traceability gaps remain diagnostics and separate metrics; they are not counted a second time inside `Delivery Pass Rate`.",
        f"- `{ARTIFACT_DERIVED_TRACE_LABEL}` is an initial metric derived from current sidecars, not the formal frozen-snapshot `Traceable Claim Rate v1`.",
        "",
        "## Core Metrics",
        "",
        "| Metric | Overall | US | HK | CN-A |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for key, label in [
        ("delivery_pass_rate", "Delivery Pass Rate"),
        ("objective_quality_score", "Objective Quality Score"),
        ("traceable_claim_rate", ARTIFACT_DERIVED_TRACE_LABEL),
    ]:
        lines.append(
            f"| {label} | {_fmt(summary['overall'].get(key))} | "
            f"{_fmt(summary['by_market']['US'].get(key))} | {_fmt(summary['by_market']['HK'].get(key))} | "
            f"{_fmt(summary['by_market']['CN-A'].get(key))} |"
        )
    lines.extend(["", "## Coverage", ""])
    for row in records:
        detail = row.get("period") or row.get("not_evaluable_reason") or "-"
        lines.append(f"- `{row['canonical_symbol']}` ({row['market']}): `{row['status']}`; {detail}")
    lines.extend(["", "## Not Run Or Not Evaluable", ""])
    exceptions = [row for row in records if row.get("status") != "evaluated"]
    if exceptions:
        for row in exceptions:
            reason = row.get("not_evaluable_reason") or "no matching existing run"
            lines.append(f"- `{row['canonical_symbol']}`: {row['status']} - {reason}")
    else:
        lines.append("- None.")
    lines.extend(["", "## Failure Reasons", ""])
    if summary.get("failure_counts"):
        for category, count in sorted(summary["failure_counts"].items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"- `{category}`: {count}")
    else:
        lines.append("- No evaluated failures recorded.")
    lines.extend(
        [
            "",
            "## Interpretation Boundary",
            "",
            "- Phase 1 does not implement `Direct LLM` or `Single-Agent RAG`, freeze evidence snapshots, modify claim schema, or modify the Agent pipeline.",
            "- Metrics above describe only selected existing artifacts. Formal cross-system claims require the later frozen-snapshot benchmark phase.",
            "",
        ]
    )
    return "\n".join(lines)


def _metric_summary(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not records:
        return {"evaluated_count": 0, "delivery_pass_rate": None, "objective_quality_score": None, "traceable_claim_rate": None}
    quality_values = [float(row["objective_quality_score"]) for row in records if row.get("objective_quality_score") is not None]
    trace_values = [float(row["traceable_claim_rate"]) for row in records if row.get("traceable_claim_rate") is not None]
    return {
        "evaluated_count": len(records),
        "delivery_pass_rate": round(sum(1 for row in records if row.get("delivery_pass")) / len(records), 4),
        "objective_quality_score": round(sum(quality_values) / len(quality_values), 2) if quality_values else None,
        "traceable_claim_rate": round(sum(trace_values) / len(trace_values), 4) if trace_values else None,
    }


def _quality_payload(outputs: Path, reports: Path) -> tuple[Dict[str, Any], str]:
    quality = _read_dict(outputs / "quality_report.json")
    if _safe_float(quality.get("total_score")) is not None:
        return quality, "existing_quality_report"
    return evaluate_report_quality_from_paths(outputs, reports, run_dir=outputs.parent), "recomputed_read_only"


def _resolved_symbol(summary: Dict[str, Any]) -> str:
    entity = summary.get("entity_resolution", {}) if isinstance(summary.get("entity_resolution"), dict) else {}
    symbol = str(entity.get("resolved_symbol") or summary.get("symbol") or "")
    return canonical_symbol(symbol)


def _is_critical_claim(claim: Dict[str, Any]) -> bool:
    section = str(claim.get("section_name") or "").lower()
    numeric = claim.get("numeric_values")
    return any(marker in section for marker in CRITICAL_SECTION_MARKERS) or bool(isinstance(numeric, dict) and numeric)


def _numeric_lineage_ok(
    claim: Dict[str, Any],
    lineage_ids: set[str] | None = None,
    numeric_audit: Dict[str, Any] | None = None,
) -> bool:
    numeric = claim.get("numeric_values")
    if not isinstance(numeric, dict) or not numeric:
        return True
    recorded = [
        str(value)
        for key in ("metric_lineage_ids", "input_metric_lineage_ids")
        for value in (claim.get(key) or [])
        if str(value)
    ]
    has_lineage_contract = "metric_lineage_ids" in claim or "input_metric_lineage_ids" in claim
    available = lineage_ids or set()
    if has_lineage_contract and not recorded:
        return False
    if available and (not recorded or not all(value in available for value in recorded)):
        return False
    if not _numeric_audit_claim_passed(str(claim.get("claim_id") or ""), numeric_audit or {}):
        return False
    return True


def _has_used_citation(claim_id: str, evidence_id: str, citations: List[Dict[str, Any]], report_text: str) -> bool:
    for citation in citations:
        if str(citation.get("evidence_id") or "") != evidence_id:
            continue
        claim_ids = [str(item) for item in citation.get("claim_ids", [])] if isinstance(citation.get("claim_ids"), list) else []
        if claim_ids and claim_id not in claim_ids:
            continue
        return _citation_used(citation, report_text)
    return False


def _citation_used(citation: Dict[str, Any], report_text: str) -> bool:
    del report_text
    return citation.get("used_in_report") is True


def _metric_lineage_ids(financial_metrics: Dict[str, Any]) -> set[str]:
    rows = financial_metrics.get("metrics", []) if isinstance(financial_metrics, dict) else []
    if not isinstance(rows, list):
        return set()
    return {
        str(row.get("metric_lineage_id"))
        for row in rows
        if isinstance(row, dict) and str(row.get("metric_lineage_id") or "")
    }


def _numeric_audit_claim_passed(claim_id: str, audit: Dict[str, Any]) -> bool:
    if not audit:
        return True
    rows = audit.get("details", []) if isinstance(audit.get("details"), list) else audit.get("claims", [])
    if isinstance(rows, list):
        matching = [row for row in rows if isinstance(row, dict) and str(row.get("claim_id") or "") == claim_id]
        if matching:
            return all(bool(row.get("supported", row.get("passed", False))) for row in matching)
    failed_ids = audit.get("failed_claim_ids", [])
    return not isinstance(failed_ids, list) or claim_id not in {str(value) for value in failed_ids}


def _has_section(report_text: str, headings: Iterable[str]) -> bool:
    for heading in headings:
        match = re.search(rf"(?im)^##\s*.*{re.escape(heading)}.*$", report_text)
        if match:
            following = report_text[match.end() :]
            body = re.split(r"(?im)^##\s+", following, maxsplit=1)[0].strip()
            return bool(body and not any(marker in body for marker in ("暂无结论", "暂无可验证结论", "待补充")))
    return False


def _has_three_statements_or_disclosed_gap(report_text: str) -> bool:
    lowered = report_text.lower()
    income = any(marker in lowered for marker in ("利润表", "income statement", "净利润", "收入"))
    balance = any(marker in lowered for marker in ("资产负债表", "balance sheet", "总资产", "股东权益"))
    cash_flow = any(marker in lowered for marker in ("现金流量表", "cash flow", "经营现金流", "自由现金流"))
    gap = any(marker in lowered for marker in ("现金流缺口", "三表缺口", "不可获得", "not available", "data gap"))
    return income and balance and (cash_flow or gap)


def _has_valuation_or_unavailable_reason(report_text: str) -> bool:
    lowered = report_text.lower()
    return any(
        marker in lowered
        for marker in ("估值", "valuation", "p/e", "p/b", "市盈率", "市净率", "估值不可用", "valuation unavailable")
    )


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number


def _read_dict(path: Path) -> Dict[str, Any]:
    value = _read_json(path, {})
    return dict(value) if isinstance(value, dict) else {}


def _read_list(path: Path) -> List[Dict[str, Any]]:
    value = _read_json(path, [])
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}" if value <= 1 else f"{value:.2f}"
    return str(value)
