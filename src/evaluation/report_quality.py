"""Objective quality evaluation for generated company research reports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List

from src.agents.research_blackboard import quality_generalization_checks


GROUP_WEIGHTS = {
    "structure": 0.16,
    "evidence": 0.20,
    "financial": 0.16,
    "multimodal": 0.10,
    "professional_depth": 0.20,
    "content_depth": 0.08,
    "compliance": 0.10,
}

EMPTY_MARKERS = ("cannot_verify", "no_conclusion", "cannot_judge", "pending", "N/A")
SCI_NOTATION_RE = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d+(?:\.\d+)?[eE][+-]\d+(?![A-Za-z0-9_])")


@dataclass
class RunPaths:
    run_dir: Path
    outputs_dir: Path
    reports_dir: Path


def evaluate_report_quality(run_dir: str | Path) -> Dict[str, Any]:
    paths = resolve_run_paths(run_dir)
    return evaluate_report_quality_from_paths(paths.outputs_dir, paths.reports_dir, paths.run_dir)


def evaluate_report_quality_from_paths(
    outputs_dir: str | Path,
    reports_dir: str | Path,
    run_dir: str | Path | None = None,
) -> Dict[str, Any]:
    paths = RunPaths(
        run_dir=Path(run_dir) if run_dir is not None else Path(outputs_dir),
        outputs_dir=Path(outputs_dir),
        reports_dir=Path(reports_dir),
    )
    artifacts = load_quality_artifacts(paths)
    issues: List[Dict[str, Any]] = []
    scores = {
        "structure": _score_structure(artifacts, issues),
        "evidence": _score_evidence(artifacts, issues),
        "financial": _score_financial(artifacts, issues),
        "multimodal": _score_multimodal(artifacts, issues),
        "professional_depth": _score_professional_depth(artifacts, issues),
        "content_depth": _score_content_depth(artifacts, issues),
        "compliance": _score_compliance(artifacts, issues),
    }
    _check_delivery_policy(artifacts, issues)
    _check_currency_policy(artifacts, issues)
    _check_pdf_rag_policy(artifacts, issues)
    _valuation_consistency_check(artifacts, issues)
    generalization_checks = quality_generalization_checks(artifacts)
    _check_generalization_policy(generalization_checks, issues)
    total = round(sum(scores[key] * GROUP_WEIGHTS[key] for key in GROUP_WEIGHTS), 4)
    required = _required_gate_checks(artifacts, issues)
    fatal_count = sum(1 for issue in issues if issue["severity"] == "fatal")
    blocker_count = sum(1 for issue in issues if issue["severity"] == "blocker")
    objective_pass = bool(total >= 0.82 and fatal_count == 0 and blocker_count == 0 and required["passed"])
    report = {
        "schema_version": "quality_report.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_dir": str(paths.run_dir),
        "outputs_dir": str(paths.outputs_dir),
        "reports_dir": str(paths.reports_dir),
        "total_score": total,
        "objective_pass": objective_pass,
        "scores": scores,
        "weights": GROUP_WEIGHTS,
        "issue_counts": {
            "fatal": fatal_count,
            "blocker": blocker_count,
            "warning": sum(1 for issue in issues if issue["severity"] == "warning"),
            "info": sum(1 for issue in issues if issue["severity"] == "info"),
        },
        "required_checks": required,
        "generalization_checks": generalization_checks,
        "top_issues": _top_issues(issues),
        "issues": issues,
        "artifact_counts": {
            "claims": len(artifacts["claims"]),
            "evidence": len(artifacts["evidence"]),
            "tables": len(artifacts["tables"]),
            "charts": len(artifacts["charts"]),
            "pdf_sections": len(artifacts["pdf_sections"]),
            "citations": len(artifacts["citations"]),
        },
    }
    return report


def write_quality_outputs(run_dir: str | Path, report: Dict[str, Any] | None = None) -> Dict[str, str]:
    paths = resolve_run_paths(run_dir)
    return write_quality_outputs_for_paths(paths.outputs_dir, paths.reports_dir, report or evaluate_report_quality(run_dir))


def write_quality_outputs_for_paths(
    outputs_dir: str | Path,
    reports_dir: str | Path,
    report: Dict[str, Any],
) -> Dict[str, str]:
    paths = RunPaths(run_dir=Path(outputs_dir), outputs_dir=Path(outputs_dir), reports_dir=Path(reports_dir))
    quality = report
    paths.outputs_dir.mkdir(parents=True, exist_ok=True)
    json_path = paths.outputs_dir / "quality_report.json"
    md_path = paths.outputs_dir / "quality_report.md"
    issues_path = paths.outputs_dir / "quality_issues.jsonl"
    json_path.write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_quality_markdown(quality), encoding="utf-8")
    issues_path.write_text(
        "\n".join(json.dumps(issue, ensure_ascii=False) for issue in quality.get("issues", [])) + "\n",
        encoding="utf-8",
    )
    return {
        "quality_report": str(json_path),
        "quality_report_md": str(md_path),
        "quality_issues": str(issues_path),
    }


def render_quality_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# Report Quality Evaluation",
        "",
        f"- objective_pass: `{report.get('objective_pass')}`",
        f"- total_score: `{report.get('total_score')}`",
        f"- run_dir: `{report.get('run_dir')}`",
        "",
        "## Scores",
        "",
    ]
    for key, value in dict(report.get("scores", {})).items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Required Checks", ""])
    for key, value in dict(report.get("required_checks", {})).items():
        if key != "details":
            lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Generalization Checks", ""])
    for key, value in dict(report.get("generalization_checks", {})).items():
        if isinstance(value, dict):
            lines.append(f"- {key}: `{value.get('passed')}`")
    lines.extend(["", "## Top Issues", ""])
    issues = report.get("top_issues", []) or []
    if not issues:
        lines.append("- No issues.")
    for issue in issues:
        lines.append(f"- **{issue.get('severity')} / {issue.get('category')}**: {issue.get('message')}")
    return "\n".join(lines) + "\n"


def resolve_run_paths(run_dir: str | Path) -> RunPaths:
    root = Path(run_dir)
    if (root / "company" / "outputs").exists():
        outputs = root / "company" / "outputs"
        reports = root / "company" / "reports"
        return RunPaths(run_dir=root, outputs_dir=outputs, reports_dir=reports)
    if root.name == "outputs":
        reports = root.parent / "reports"
        return RunPaths(run_dir=root.parent, outputs_dir=root, reports_dir=reports)
    if (root / "outputs").exists():
        return RunPaths(run_dir=root, outputs_dir=root / "outputs", reports_dir=root / "reports")
    return RunPaths(run_dir=root, outputs_dir=root, reports_dir=root.parent / "reports")


def load_quality_artifacts(paths: RunPaths) -> Dict[str, Any]:
    return {
        "summary": _read_json(paths.outputs_dir / "run_summary.json", {}),
        "claims": _as_list(_read_json(paths.outputs_dir / "claims.json", [])),
        "evidence": _as_list(_read_json(paths.outputs_dir / "evidence.json", [])),
        "citations": _as_list(_read_json(paths.outputs_dir / "citations.json", [])),
        "tables": _as_list(_read_json(paths.outputs_dir / "tables.json", [])),
        "financial_metrics": _read_json(paths.outputs_dir / "financial_metrics.json", {}),
        "currency_audit": _read_json(paths.outputs_dir / "currency_audit.json", {}),
        "valuation_model": _read_json(paths.outputs_dir / "valuation_model.json", {}),
        "valuation_sensitivity": _read_json(paths.outputs_dir / "valuation_sensitivity.json", {}),
        "charts": _as_list(_read_json(paths.outputs_dir / "charts.json", [])),
        "pdf_sections": _as_list(_read_json(paths.outputs_dir / "pdf_sections.json", [])),
        "pdf_section_summaries": _as_list(_read_json(paths.outputs_dir / "pdf_section_summaries.json", [])),
        "pdf_extraction_audit": _read_json(paths.outputs_dir / "pdf_extraction_audit.json", {}),
        "official_evidence_manifest": _read_json(paths.outputs_dir / "official_evidence_manifest.json", {}),
        "evidence_coverage": _read_json(paths.outputs_dir / "evidence_coverage.json", {}),
        "profile": _read_json(paths.outputs_dir / "company_profile_extracted.json", {}),
        "verification": _read_json(paths.outputs_dir / "verification_report.json", {}),
        "scorecard": _read_json(paths.outputs_dir / "company_report_scorecard.json", {}),
        "search_meta": _read_json(paths.outputs_dir / "search_meta.json", {}),
        "agent_collaboration_trace": _read_json(paths.outputs_dir / "agent_collaboration_trace.json", {}),
        "research_blackboard": _read_json(paths.outputs_dir / "research_blackboard.json", {}),
        "report_md": _read_text(paths.reports_dir / "report.md"),
        "report_html": _read_text(paths.reports_dir / "report.html"),
        "report_json": _read_json(paths.reports_dir / "report.json", {}),
        "section_dossiers": _read_json(paths.outputs_dir / "section_dossiers.json", {}),
    }


def _score_structure(artifacts: Dict[str, Any], issues: List[Dict[str, Any]]) -> float:
    text = _report_text(artifacts)
    required = {
        "executive_summary": ("executive_summary", "summary", "核心", "摘要", "执行摘要"),
        "business_profile": ("business", "operation", "segment", "product", "业务"),
        "financial_analysis": ("financial", "income", "balance", "cashflow", "财务"),
        "valuation": ("valuation", "p/e", "p/b", "估值"),
        "risk": ("risk", "风险"),
        "investment_conclusion": ("investment_conclusion", "recommendation", "rating", "conclusion", "评级"),
    }
    present = {key: _contains_any(text, terms) for key, terms in required.items()}
    for key, ok in present.items():
        if not ok:
            _issue(issues, "blocker", "structure", f"missing required section: {key}")
    if any(marker in text for marker in EMPTY_MARKERS):
        _issue(issues, "blocker", "structure", "report contains empty placeholder conclusions or temporarily unverifiable conclusions")
    empty_count = sum(text.count(marker) for marker in EMPTY_MARKERS)
    if empty_count >= 3:
        _issue(issues, "fatal", "structure", f"too many empty markers: {empty_count}")
    return round(sum(1 for ok in present.values() if ok) / max(1, len(required)), 4)


def _score_evidence(artifacts: Dict[str, Any], issues: List[Dict[str, Any]]) -> float:
    claims = artifacts.get("claims", []) if isinstance(artifacts.get("claims"), list) else []
    evidence = artifacts.get("evidence", []) if isinstance(artifacts.get("evidence"), list) else []
    citations = artifacts.get("citations", []) if isinstance(artifacts.get("citations"), list) else []
    text = _report_text(artifacts)
    if not claims:
        _issue(issues, "fatal", "evidence", "claims is empty")
        return 0.0
    covered = 0
    for claim in claims:
        eids = claim.get("evidence_ids") if isinstance(claim, dict) else []
        if isinstance(eids, list) and eids:
            covered += 1
    coverage = covered / max(1, len(claims))
    citation_in_body = 1.0 if re.search(r"(ev_|evidence|citation|来源|引用|\[\d+\])", text, re.I) else 0.0
    if citations and citation_in_body == 0.0:
        _issue(issues, "blocker", "evidence", "citations exist but no citation marks in body")
    primary = sum(1 for item in evidence if isinstance(item, dict) and _is_primary_source(item))
    primary_ratio = primary / max(1, len(evidence))
    if primary_ratio < 0.35:
        _issue(issues, "warning", "evidence", f"primary source ratio low: {primary_ratio:.2f}")
    return round(0.55 * coverage + 0.25 * min(1.0, len(citations) / max(1, len(claims))) + 0.2 * max(citation_in_body, primary_ratio), 4)


def _score_financial(artifacts: Dict[str, Any], issues: List[Dict[str, Any]]) -> float:
    tables = artifacts["tables"]
    metrics = artifacts["financial_metrics"]
    text = _report_text(artifacts)
    statements = _statement_names_from_tables(tables)
    has_income = any("income" in item for item in statements)
    has_balance = any("balance" in item for item in statements)
    has_cashflow = any("cash" in item for item in statements) or _has_cashflow_gap_explained(text)
    for ok, name in [(has_income, "income"), (has_balance, "balance"), (has_cashflow, "cashflow")]:
        if not ok:
            _issue(issues, "blocker", "financial", f"missing {name} summary")
    if SCI_NOTATION_RE.search(text):
        _issue(issues, "blocker", "financial", "report contains scientific notation, unprofessional financial display")
    if not re.search(r"(billion|million|pct|bps|%)", text, flags=re.IGNORECASE):
        _issue(issues, "warning", "financial", "report lacks clear unit or percentage expression")
    if re.search(r"0700\.HK|Tencent|腾讯", text, re.I) and re.search(r"751,?766,?000,?000\s+USD|751\.?766\s+billion\s+USD", text, re.I):
        _issue(issues, "blocker", "currency_unit_mismatch", "Tencent RMB financial statement amount is labeled USD")
    metric_score = 1.0 if metrics else 0.45
    period_alignment = _period_alignment_score(artifacts, issues)
    table_score = (int(has_income) + int(has_balance) + int(has_cashflow)) / 3
    return round(0.45 * table_score + 0.25 * metric_score + 0.2 * period_alignment + 0.1 * (0 if SCI_NOTATION_RE.search(text) else 1), 4)


def _score_multimodal(artifacts: Dict[str, Any], issues: List[Dict[str, Any]]) -> float:
    charts = artifacts["charts"]
    tables = artifacts["tables"]
    text = _report_text(artifacts)
    if not charts:
        _issue(issues, "blocker", "multimodal", "missing chart artifacts")
    useful = 0
    for chart in charts:
        title = str(chart.get("title") or chart.get("chart_id") or "") if isinstance(chart, dict) else ""
        if _contains_any(title, ("revenue", "income", "cash", "margin", "metrics", "profit")):
            useful += 1
    if charts and useful == 0:
        _issue(issues, "warning", "multimodal", "charts do not clearly serve financial analysis")
    figure_mentioned = 1.0 if _contains_any(text, ("figure", "chart", "table", "graph")) else 0.0
    return round(0.45 * min(1.0, len(charts) / 2) + 0.25 * min(1.0, useful / 1) + 0.2 * min(1.0, len(tables) / 3) + 0.1 * figure_mentioned, 4)


CONTENT_DEPTH_THRESHOLDS = {
    "executive_summary": 120,
    "business_overview": 160,
    "financial_analysis": 220,
    "peer_compare": 120,
    "valuation": 180,
    "risks": 160,
    "conclusion": 160,
}

SECTION_HEADING_MAP = {
    "executive_summary": "执行摘要",
    "business_overview": "业务概览",
    "ownership_governance": "governance",
    "strategy_business": "strategy",
    "three_statement_summary": "三表摘要",
    "financial_analysis": "财务分析",
    "peer_compare": "同行对比",
    "valuation": "估值观察",
    "valuation_sensitivity": "估值敏感性",
    "risks": "风险评估",
    "conclusion": "投资结论",
}

TEMPLATE_PHRASES = [
    "template_placeholder_long_term",
    "template_placeholder_listed_company",
    "持续深耕",
    "巩固核心竞争力",
]

HALF_SENTENCE_MARKERS = [
    "half_sentence",
    "incomplete",
    "needs_attention",
]

# Internal debug/ID patterns that must never appear in the final report body
DEBUG_LEAK_PATTERNS = [
    "metric_count",
    "rejected_metric_count",
    "statement_line_item_count",
    "Risk-related claim evidence count",
    "supported metrics",
    "cl_",
]

# Regex patterns for raw SEC companyfacts dump (require 6+ digits to avoid false positives)
COMPANYFACTS_DUMP_PATTERNS_RE = [
    r'Revenues\d{6,}',
    r'NetIncomeLoss\d{6,}',
    r'CashAndCashEquivalentsAtCarryingValue',
    r'NetCashProvidedByUsedInOperatingActivities',
    r'Assets\d{6,}',
    r'Liabilities\d{6,}',
    r'companyfacts?\d{6,}',
]

# Internal ID patterns that must never appear in rendered HTML
INTERNAL_ID_HTML_PATTERNS = [
    r'cl_\d{4}',
    r'claim_id',
    r'statement_line_item_count',
    r'支持结论',
    r'supported claims',
]

MOJIBAKE_HTML_PATTERNS = [
    r'[\uFFFD]',
    r'[鐠缂閹锟]',
    r'[\ue000-\uf8ff]',
    r'(缁撹|璇佹嵁|鏉ユ簮|鎽樿)',
    r'[ÃÂÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖ×ØÙÚÛÜÝÞßàáâãäåæçèéêëìíîïðñòóôõö÷øùúûüýþÿ]',
]

CHART_INTERNAL_LABEL_PATTERNS = [
    r'pe_ttm',
    r'market_cap_trillion',
    r'revenue_growth_pct',
    r'gross_margin_pct',
    r'net_margin_pct',
]


def _score_content_depth(artifacts: Dict[str, Any], issues: List[Dict[str, Any]]) -> float:
    """Check each core section for minimum content depth using section_dossiers."""
    section_dossiers = artifacts.get("section_dossiers", {})
    if not isinstance(section_dossiers, dict) or not section_dossiers:
        return 1.0  # no dossiers available, skip check

    text = _report_text(artifacts)
    total_checks = len(CONTENT_DEPTH_THRESHOLDS)
    passes = 0

    for section_key, threshold in CONTENT_DEPTH_THRESHOLDS.items():
        heading = SECTION_HEADING_MAP.get(section_key, "")
        if not heading:
            continue
        body = _section_body(text, (heading,))
        if not body:
            _issue(issues, "warning", "content_depth", f"section {heading} missing content depth")
            continue
        chinese_chars = len(re.sub(r"[\s\n\r#\-*:：，、。）（\[\]【】\"''a-zA-Z0-9]", "", body))
        if chinese_chars >= threshold:
            passes += 1
        else:
            dossier = section_dossiers.get(section_key, {})
            if not isinstance(dossier, dict):
                passes += 1
                continue
            min_content_level = dossier.get("min_content_level", "")
            if min_content_level == "data_gap":
                passes += 1  # data_gap sections are allowed to be short
                continue
            _issue(issues, "blocker", "content_depth",
                   f"{heading} content insufficient: only {chinese_chars} chars (threshold {threshold})")

    # Template phrase detection
    for phrase in TEMPLATE_PHRASES:
        if phrase in text:
            _issue(issues, "blocker", "content_depth", f"report contains template phrase: {phrase}")

    # Half-sentence detection
    for marker in HALF_SENTENCE_MARKERS:
        if marker in text:
            _issue(issues, "blocker", "content_depth", f"report contains half-sentence marker: {marker}")

    # Debug/internal ID leakage detection
    for pattern in DEBUG_LEAK_PATTERNS:
        if pattern in text:
            _issue(issues, "blocker", "content_depth", f"report contains debug leakage: {pattern}")
    if _contains_any(text, ("Item 1A", "Risk Factors", "Management's Discussion", "Our business", "We face intense competition")) and len(re.findall(r"\b[A-Za-z]{5,}\b", text)) > 120:
        _issue(issues, "blocker", "raw_english_annual_section_leak", "report appears to contain raw English annual-report sections")
    for key in ("revenue_growth_pct", "adjusted_net_income", "non_recurring_gain"):
        if key in text:
            _issue(issues, "blocker", "internal_metric_key_leak", f"internal metric key leaked: {key}")

    # Raw SEC companyfacts dump detection
    for pat in COMPANYFACTS_DUMP_PATTERNS_RE:
        if re.search(pat, text):
            _issue(issues, "blocker", "content_depth", f"report contains raw companyfacts dump: {pat}")

    # Internal ID in rendered HTML
    for pat in INTERNAL_ID_HTML_PATTERNS:
        if re.search(pat, text):
            _issue(issues, "blocker", "content_depth", f"report HTML contains internal ID: {pat}")

    if _has_orphan_numeric_summary(text):
        _issue(issues, "blocker", "content_depth", "orphan_numeric_summary")

    for pat in MOJIBAKE_HTML_PATTERNS:
        if re.search(pat, text):
            _issue(issues, "blocker", "content_depth", f"mojibake_in_user_html: {pat}")

    for pat in CHART_INTERNAL_LABEL_PATTERNS:
        if re.search(pat, text, flags=re.IGNORECASE):
            _issue(issues, "blocker", "content_depth", f"chart_internal_labels: {pat}")

    if total_checks == 0:
        return 1.0
    return round(passes / total_checks, 4)


def _has_orphan_numeric_summary(text: str) -> bool:
    match = re.search(r"(?ms)^##\s+.*?(?:执行摘要|摘要|鎵ц).*?\n(?P<body>.*?)(?=^##\s+|\Z)", text)
    if not match:
        return False
    body = match.group("body")
    numeric_bullets = re.findall(r"(?m)^\s*[-*]\s*\d+(?:\.\d+)?\s*$", body)
    prose = re.sub(r"(?m)^\s*[-*]\s*\d+(?:\.\d+)?\s*$", "", body)
    prose_chars = re.sub(r"[\s#*\-:：，、。()\[\]0-9a-zA-Z]", "", prose)
    return len(numeric_bullets) >= 2 and len(prose_chars) < 18


def _score_professional_depth(artifacts: Dict[str, Any], issues: List[Dict[str, Any]]) -> float:
    text = _report_text(artifacts)
    profile = artifacts["profile"]
    claims = artifacts.get("claims", []) if isinstance(artifacts.get("claims"), list) else []

    def _section_has_evidence_ids(section: str) -> bool:
        """Check if any claim for section has non-empty evidence_ids."""
        for c in claims:
            if str(c.get("section_name", "")) == section:
                eids = c.get("evidence_ids", [])
                if isinstance(eids, list) and any(str(e).strip() for e in eids):
                    return True
        return False

    def _has_claims_for_section(section: str, claims_list: list) -> bool:
        """Check if any claims exist for a given section."""
        for c in claims_list:
            if str(c.get("section_name", "")) == section:
                return True
        return False

    checks = {
        "business_profile": bool(profile) or _contains_any(text, ("business", "product", "segment", "operation", "业务")),
        "peer_compare": _contains_any(text, ("peer", "competitor", "comparable", "同行", "同行比较")),
        "valuation": _contains_any(text, ("valuation", "P/E", "P/B", "P/S", "估值")),
        "sensitivity": _contains_any(text, ("sensitivity", "scenario", "敏感性")),
        "risk": _contains_any(text, ("risk", "exposure", "风险")),
        "investment": _contains_any(text, ("rating", "buy", "hold", "outperform", "underperform", "评级", "投资建议")),
    }
    for key, ok in checks.items():
        if not ok:
            severity = "blocker" if key in {"business_profile", "risk", "investment"} else "warning"
            _issue(issues, severity, "professional_depth", f"professional_depth missing: {key}")
    if _section_is_framework_only(text, ("peer comparison", "peer compare", "同行对比", "同行比较")):
        _issue(issues, "blocker", "professional_depth", "peer comparison is framework-only, lacks actionable conclusion")
    if checks.get("peer_compare") and _has_claims_for_section("peer_compare", claims) and not _section_has_evidence_ids("peer_compare"):
        _issue(issues, "blocker", "professional_depth", "peer_compare claims have empty evidence_ids")
    if _section_is_framework_only(text, ("sensitivity analysis", "估值敏感性", "敏感性分析")):
        _issue(issues, "blocker", "professional_depth", "sensitivity analysis is framework-only, lacks variable direction")
    if _valuation_is_unusable_without_reason(text) and not _blackboard_valuation_gap_is_explained(artifacts):
        _issue(issues, "blocker", "professional_depth", "valuation missing but no reason given")
    if not _investment_conclusion_has_direction_and_reason(text):
        _issue(issues, "blocker", "professional_depth", "investment conclusion lacks direction and reason")
    return round(sum(1 for ok in checks.values() if ok) / len(checks), 4)


def _score_compliance(artifacts: Dict[str, Any], issues: List[Dict[str, Any]]) -> float:
    text = _report_text(artifacts)
    checks = {
        "risk_disclosure": _contains_any(text, ("risk disclosure", "risk factor", "风险")),
        "source_disclosure": _contains_any(text, ("source", "citation", "reference", "来源", "资料来源")),
        "rating_explanation": _contains_any(text, ("rating", "recommendation", "target", "评级", "投资建议")),
        "use_limitation": _contains_any(text, ("not investment advice", "disclaimer", "limitation", "不构成投资建议", "仅供参考")),
        "conflict_statement": _contains_any(text, ("conflict", "independent", "disclosure", "利益冲突", "独立性")),
    }
    for key, ok in checks.items():
        if not ok:
            _issue(issues, "warning", "compliance", f"missing compliance disclosure: {key}")
    return round(sum(1 for ok in checks.values() if ok) / len(checks), 4)


def _check_delivery_policy(artifacts: Dict[str, Any], issues: List[Dict[str, Any]]) -> None:
    summary = artifacts.get("summary", {}) if isinstance(artifacts.get("summary"), dict) else {}
    entity = summary.get("entity_resolution", {}) if isinstance(summary.get("entity_resolution"), dict) else {}
    resolved_symbol = str(entity.get("resolved_symbol") or summary.get("symbol") or "").strip()
    confidence = float(entity.get("confidence") or entity.get("resolution_confidence") or 0.0)
    if not resolved_symbol:
        _issue(issues, "blocker", "delivery_policy", "cannot resolve listed company symbol, cannot generate formal company research report")
    elif confidence and confidence < 0.45:
        _issue(issues, "blocker", "delivery_policy", f"entity resolution confidence too low: {confidence:.2f}")

    report_text = _report_text(artifacts)
    memory_trace = artifacts.get("agent_collaboration_trace", {})
    memory_text = json.dumps(memory_trace, ensure_ascii=False) if isinstance(memory_trace, dict) else ""
    if "DurableMemory" in report_text or "[DurableMemory]" in report_text:
        _issue(issues, "blocker", "delivery_policy", "report text appears to use memory content as factual source")
    if memory_text and "facts require evidence/citation/verifier" not in memory_text:
        _issue(issues, "warning", "delivery_policy", "multi-agent trace does not clarify memory cannot replace factual evidence")

    engines = _search_engines_used(artifacts.get("search_meta", {}), summary)
    if len(set(engines)) < 2:
        _issue(issues, "warning", "delivery_policy", "fewer than 2 search engines used; at least 2 data sources recommended")
    if engines and _only_local_sources(engines) and not _contains_any(report_text, ("data gap", "source gap", "unavailable", "limited data")):
        _issue(issues, "blocker", "delivery_policy", "only local sources used but report does not acknowledge data gap")

    if (
        _contains_any(report_text, ("continue to monitor", "cautious observation", "neutral"))
        and not _contains_any(report_text, ("reason", "driver", "competition", "valuation", "risk"))
    ):
        _issue(issues, "blocker", "delivery_policy", "investment conclusion has direction but lacks reason, growth driver, competitive pressure or valuation constraint")

    evidence_coverage = artifacts.get("evidence_coverage", {}) if isinstance(artifacts.get("evidence_coverage"), dict) else {}
    if evidence_coverage.get("degrade_required") is True:
        missing = ", ".join(str(item) for item in evidence_coverage.get("missing_requirements", [])[:6])
        _issue(
            issues,
            "blocker",
            "official_evidence",
            f"Official evidence is insufficient for formal A/H delivery; degrade strong conclusions: {missing}",
        )


def _check_currency_policy(artifacts: Dict[str, Any], issues: List[Dict[str, Any]]) -> None:
    audit = artifacts.get("currency_audit", {}) if isinstance(artifacts.get("currency_audit"), dict) else {}
    for blocker in audit.get("blockers", []) if isinstance(audit.get("blockers"), list) else []:
        _issue(issues, "blocker", str(blocker), f"currency audit blocker: {blocker}")

    metrics = artifacts.get("financial_metrics", {}) if isinstance(artifacts.get("financial_metrics"), dict) else {}
    summary = artifacts.get("summary", {}) if isinstance(artifacts.get("summary"), dict) else {}
    symbol = str(audit.get("symbol") or summary.get("symbol") or "").upper()
    market = str(audit.get("market") or "")
    if not market and symbol.endswith(".HK"):
        market = "hk"
    if not market and (symbol.endswith(".SS") or symbol.endswith(".SZ")):
        market = "cn_a"

    for metric in metrics.get("metrics", []) if isinstance(metrics.get("metrics"), list) else []:
        if not isinstance(metric, dict):
            continue
        name = str(metric.get("metric_name") or "")
        unit = str(metric.get("unit") or metric.get("currency") or "").upper()
        source_type = str(metric.get("source_type") or "").lower()
        if market in {"hk", "cn_a"} and name in {"revenue", "net_income", "total_assets", "free_cash_flow"} and unit == "USD" and source_type in {"market_api", "market_data", "yahoo_finance"}:
            _issue(issues, "blocker", "currency_unit_mismatch", f"{symbol} {name} from {source_type} is labeled USD")

    valuation = artifacts.get("valuation_model", {}) if isinstance(artifacts.get("valuation_model"), dict) else {}
    status = str(valuation.get("valuation_status") or valuation.get("error") or "")
    if status in {"blocked_due_to_currency_mismatch", "missing_fx_rate_for_cross_currency_valuation"}:
        _issue(issues, "blocker", status, f"valuation blocked by currency gate: {status}")
    if market in {"hk", "cn_a"} and str(valuation.get("currency") or "").upper() == "USD":
        _issue(issues, "blocker", "valuation_currency_mismatch", f"{symbol} non-US valuation model is labeled USD")


def _valuation_consistency_check(artifacts: Dict[str, Any], issues: List[Dict[str, Any]]) -> None:
    valuation_model = artifacts.get("valuation_model", {})
    if not isinstance(valuation_model, dict):
        return
    model = valuation_model.get("valuation_model", valuation_model)
    if not isinstance(model, dict):
        return
    dcf_part = model.get("dcf_model", {})
    if not isinstance(dcf_part, dict):
        return
    dcf_value = dcf_part.get("equity_value_billion") or dcf_part.get("value_billion") or dcf_part.get("enterprise_value_billion")
    blended = model.get("blended_equity_value_billion")
    try:
        dcf_val = float(dcf_value) if dcf_value is not None else None
        blended_val = float(blended) if blended is not None else None
    except (TypeError, ValueError):
        return
    if dcf_val is None or blended_val is None or dcf_val <= 0 or blended_val <= 0:
        return
    divergence = abs(dcf_val - blended_val) / max(dcf_val, blended_val)
    if divergence > 0.50:
        text = _report_text(artifacts)
        has_explanation = _contains_any(
            text,
            (
                "valuation_method",
                "valuation_difference",
                "dcf_vs_composite",
                "method_diff",
                "valuation_model_diff",
                "valuation_methods",
                "valuation_range",
                "valuation_step",
                "估值方法差异",
                "估值区间",
                "方法分歧",
            ),
        )
        severity = "warning" if has_explanation else "blocker"
        _issue(
            issues,
            severity,
            "valuation_consistency",
            f"DCF ({dcf_val:.2f}B) vs composite ({blended_val:.2f}B) divergence {divergence*100:.0f}%",
        )


def _check_pdf_rag_policy(artifacts: Dict[str, Any], issues: List[Dict[str, Any]]) -> None:
    audit = artifacts.get("pdf_extraction_audit", {}) if isinstance(artifacts.get("pdf_extraction_audit"), dict) else {}
    summaries = artifacts.get("pdf_section_summaries", []) if isinstance(artifacts.get("pdf_section_summaries"), list) else []
    text = _report_text(artifacts)
    if audit and int(audit.get("page_count") or 0) > 0 and not summaries:
        _issue(issues, "blocker", "pdf_rag", "PDF is cached but pdf_section_summaries.json is empty")
    if audit and int(audit.get("page_count") or 0) > 8 and int(audit.get("extracted_page_count") or 0) <= 8 and not audit.get("section_map"):
        _issue(issues, "blocker", "pdf_rag", "PDF heading discovery appears limited to early pages")
    if audit and audit.get("failure_reason") and "本节暂无充足的可验证证据支持详细分析" in text:
        _issue(issues, "blocker", "pdf_rag", "report uses generic PDF gap despite a specific pdf_extraction_audit failure reason")
    if re.search(r"\b([A-Z0-9]{4,6}\.[A-Z]{2})（\1）", text):
        _issue(issues, "blocker", "pdf_rag", "report repeats symbol in company display name")
def _check_generalization_policy(checks: Dict[str, Any], issues: List[Dict[str, Any]]) -> None:
    for key, payload in checks.items():
        row = payload if isinstance(payload, dict) else {}
        if row.get("passed") is True:
            continue
        severity = "blocker" if key in {"identity_consistency", "period_consistency", "pre_write_critic_passed"} else "warning"
        _issue(issues, severity, "generalization", f"generalization check failed: {key}")


def _search_engines_used(search_meta: Any, summary: Dict[str, Any]) -> List[str]:
    engines: List[str] = []
    raw = summary.get("search_engines", [])
    if isinstance(raw, list):
        engines.extend(str(item) for item in raw if str(item))
    meta = search_meta.get("engine_meta", search_meta) if isinstance(search_meta, dict) else {}
    if isinstance(meta, dict):
        engines.extend(str(key) for key in meta.keys())
    return [item for item in engines if item]


def _only_local_sources(engines: List[str]) -> bool:
    if not engines:
        return True
    remote = {
        "sec_edgar",
        "yahoo_finance",
        "eastmoney",
        "eastmoney_financials",
        "cninfo_announcements",
        "exchange_announcements",
        "tavily",
        "serper",
        "metaso",
        "sogou",
    }
    return not any(engine in remote for engine in engines)


def _required_gate_checks(artifacts: Dict[str, Any], issues: List[Dict[str, Any]]) -> Dict[str, Any]:
    text = _report_text(artifacts)
    tables = artifacts["tables"]
    statements = _statement_names_from_tables(tables)
    has_three_tables = (
        any("income" in item for item in statements)
        and any("balance" in item for item in statements)
        and (any("cash" in item for item in statements) or _has_cashflow_gap_explained(text))
        and _body_has_three_statement_summary(text)
    )
    checks = {
        "non_empty_executive_summary": _contains_any(text, ("executive_summary", "summary", "核心", "摘要", "执行摘要")) and not _section_is_empty(text, ("executive_summary", "summary", "摘要", "执行摘要")),
        "non_empty_risk": _contains_any(text, ("risk", "风险")) and not _section_is_empty(text, ("risk", "风险")),
        "non_empty_investment_conclusion": _contains_any(text, ("rating", "recommendation", "conclusion", "评级")) and not _section_is_empty(text, ("conclusion", "投资建议")),
        "has_three_table_summary": has_three_tables,
        "has_business_profile": bool(artifacts["profile"]) or _contains_any(text, ("business", "product", "segment", "业务", "主营")),
        "valuation_or_reason": _contains_any(text, ("valuation", "P/E", "P/B", "P/S", "估值", "估值不可用")),
        "no_debug_leakage": not any(p in text for p in DEBUG_LEAK_PATTERNS),
        "no_template_phrases": not any(p in text for p in TEMPLATE_PHRASES),
        "no_raw_companyfacts": not any(re.search(pat, text) for pat in COMPANYFACTS_DUMP_PATTERNS_RE),
        "no_internal_id_in_html": not any(re.search(pat, text) for pat in INTERNAL_ID_HTML_PATTERNS),
    }
    for key, ok in checks.items():
        if not ok:
            _issue(issues, "fatal" if key in {"non_empty_executive_summary", "non_empty_risk", "non_empty_investment_conclusion"} else "blocker", "gate", f"quality gate failed: {key}")
    return {"passed": all(checks.values()), "details": checks}


def _report_text(artifacts: Dict[str, Any]) -> str:
    return "\n".join([str(artifacts.get("report_md") or ""), str(artifacts.get("report_html") or "")])


def _statement_name(row: Dict[str, Any]) -> str:
    return str(row.get("statement") or row.get("table_type") or row.get("source_table") or row.get("title") or "").lower()


def _statement_names_from_tables(tables: List[Any]) -> set[str]:
    names: set[str] = set()
    for row in tables:
        if not isinstance(row, dict):
            continue
        name = _statement_name(row)
        if name:
            names.add(name)
        nested_rows = row.get("rows")
        if isinstance(nested_rows, list):
            for nested in nested_rows:
                if isinstance(nested, dict):
                    nested_name = _statement_name(nested)
                    if nested_name:
                        names.add(nested_name)
    return names


def _has_cashflow_gap_explained(text: str) -> bool:
    if _contains_any(
        text,
        (
            "cash flow data gap explained",
            "cash flow statement data gap",
            "no verifiable cash flow statement rows",
            "cash conversion",
            "现金流量表缺口",
            "现金流缺口",
            "尚未取得经营现金流",
        ),
    ):
        return True
    return _contains_any(text, ("cash_flow_gap", "cash_flow_data_missing", "no_cash_flow_data", "cash_conversion", "现金流量表缺口", "现金流缺口"))


def _body_has_three_statement_summary(text: str) -> bool:
    return (
        _contains_any(text, ("income_statement", "income", "revenue", "net_income", "利润", "收入"))
        and _contains_any(text, ("balance_sheet", "balance", "total_assets", "equity", "资产", "负债"))
        and (_contains_any(text, ("cash_flow", "cashflow", "operating_cash_flow", "free_cash_flow", "现金流")) or _has_cashflow_gap_explained(text))
    )


def _section_is_framework_only(text: str, titles: Iterable[str]) -> bool:
    body = _section_body(text, titles)
    if not body:
        return False
    framework_markers = ("framework", "pending", "lack_of", "no_data", "insufficient", "missing", "框架待补", "待补", "缺少")
    conclusion_markers = ("therefore", "because", "pressure", "driver", "constraint", "better", "worse", "neutral", "positive", "cautious", "因为", "由于", "压力", "约束", "中性")
    return _contains_any(body, framework_markers) and not _contains_any(body, conclusion_markers)


def _valuation_is_unusable_without_reason(text: str) -> bool:
    if not _contains_any(text, ("valuation", "P/E", "P/B", "P/S", "估值", "市盈率", "市净率")):
        return True
    has_multiple = bool(re.search(r"(P/E|P/B|P/S|市盈率|市净率)\s*(约为|为|:|：)?\s*\d", text, flags=re.I))
    has_reason = _contains_any(text, ("valuation not available", "valuation temporarily unavailable", "no market cap", "no shares outstanding", "no net income data", "no net assets data", "估值缺失", "估值不可用"))
    return not has_multiple and not has_reason


def _blackboard_valuation_gap_is_explained(artifacts: Dict[str, Any]) -> bool:
    valuation_model = artifacts.get("valuation_model", {}) if isinstance(artifacts.get("valuation_model"), dict) else {}
    if valuation_model.get("relative_valuation") or valuation_model.get("dcf_model"):
        return True
    bb = artifacts.get("research_blackboard", {}) if isinstance(artifacts.get("research_blackboard"), dict) else {}
    role_outputs = bb.get("role_outputs", {}) if isinstance(bb.get("role_outputs"), dict) else {}
    valuation = role_outputs.get("valuation_analysis", {}) if isinstance(role_outputs.get("valuation_analysis"), dict) else {}
    status = str(valuation.get("status") or "")
    return status in {"missing", "partial"} and bool(valuation.get("missing_inputs")) and bool(valuation.get("impact_on_report"))


def _investment_conclusion_has_direction_and_reason(text: str) -> bool:
    body = _section_body(text, ("investment_conclusion", "recommendation", "rating", "投资建议", "评级"))
    if not body:
        return False
    has_direction = _contains_any(body, ("neutral", "cautious", "positive", "buy", "hold", "sell", "watch", "中性", "买入", "持有", "卖出"))
    has_reason = _contains_any(body, ("based_on", "because", "due_to", "driven_by", "driver", "pressure", "risk", "valuation", "cash_flow", "evidence", "基于", "由于", "驱动", "风险", "估值"))
    return has_direction and has_reason


def _section_body(text: str, titles: Iterable[str]) -> str:
    for title in titles:
        match = re.search(rf"(?m)^##\s*{re.escape(title)}\s*$", text)
        if not match:
            continue
        next_header = re.search(r"(?m)^##\s+", text[match.end():])
        end = match.end() + next_header.start() if next_header else len(text)
        return text[match.end():end].strip()
    return ""


def _period_alignment_score(artifacts: Dict[str, Any], issues: List[Dict[str, Any]]) -> float:
    summary_period = str(artifacts["summary"].get("period") or "").upper()
    if not summary_period:
        return 0.7
    mismatches = []
    for claim in artifacts["claims"]:
        if not isinstance(claim, dict):
            continue
        metadata = claim.get("metadata") if isinstance(claim.get("metadata"), dict) else {}
        period = str(claim.get("period") or metadata.get("period") or "").upper()
        if period and period != summary_period:
            mismatches.append(claim.get("claim_id") or period)
    if mismatches:
        _issue(issues, "warning", "financial", f"claim period may differ from target period: {mismatches[:5]}")
        return 0.55
    data_periods = _collect_data_periods(artifacts)
    other_periods = sorted(period for period in data_periods if period and period != summary_period)
    if other_periods:
        report_text = _report_text(artifacts)
        has_delay_note = _contains_any(
            report_text,
            (
                "data_lag",
                "latest_available",
                "as_of",
                "disclosure_period",
                "source_period",
                "data_cutoff",
            ),
        )
        severity = "warning" if has_delay_note else "blocker"
        _issue(
            issues,
            severity,
            "financial",
            f"target period {summary_period} differs from available data periods {other_periods[:5]}; report must disclose data lag",
        )
        return 0.7 if has_delay_note else 0.45
    return 1.0


def _collect_data_periods(artifacts: Dict[str, Any]) -> set[str]:
    periods: set[str] = set()
    for key in ["evidence", "tables"]:
        for item in artifacts.get(key, []):
            if isinstance(item, dict):
                period = str(item.get("period") or "").upper()
                if re.match(r"^20\d{2}Q[1-4]$", period):
                    periods.add(period)
    metrics = artifacts.get("financial_metrics", {})
    metric_rows = metrics if isinstance(metrics, list) else metrics.get("metrics", []) if isinstance(metrics, dict) else []
    if isinstance(metric_rows, list):
        for item in metric_rows:
            if isinstance(item, dict):
                period = str(item.get("period") or "").upper()
                if re.match(r"^20\d{2}Q[1-4]$", period):
                    periods.add(period)
    return periods


def _section_is_empty(text: str, headings: Iterable[str]) -> bool:
    for heading in headings:
        idx = text.find(heading)
        if idx < 0:
            continue
        snippet = text[idx : idx + 500]
        if any(marker in snippet for marker in EMPTY_MARKERS):
            return True
    return False


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    lowered = str(text or "").lower()
    expanded = set(str(term).lower() for term in terms)
    alias_groups = [
        ("executive_summary", "summary"),
        ("business", "product", "segment", "operation"),
        ("financial", "income", "balance", "cash_flow"),
        ("valuation", "p/e", "p/b", "p/s"),
        ("risk", "risk_disclosure", "risk_factor"),
        ("recommendation", "rating", "conclusion", "buy", "hold", "sell"),
        ("peer", "competitor", "comparable"),
        ("sensitivity", "scenario"),
        ("source", "citation", "reference"),
        ("disclaimer", "not_investment_advice", "limitation"),
        ("conflict", "independent", "disclosure"),
    ]
    for group in alias_groups:
        if any(item.lower() in expanded for item in group):
            expanded.update(item.lower() for item in group)
    return any(term in lowered for term in expanded)


def _is_primary_source(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    joined = " ".join(str(item.get(key, "")) for key in ["source_type", "trust_level", "source_url", "title"]).lower()
    return any(term in joined for term in ["primary", "sec", "edgar", "cninfo", "sse", "szse", "exchange", "eastmoney_financial"])


def _top_issues(issues: List[Dict[str, Any]], limit: int = 12) -> List[Dict[str, Any]]:
    order = {"fatal": 0, "blocker": 1, "warning": 2, "info": 3}
    return sorted(issues, key=lambda item: (order.get(item.get("severity"), 9), item.get("category", "")))[:limit]


def _issue(issues: List[Dict[str, Any]], severity: str, category: str, message: str) -> None:
    issue_id = f"{category}_{len(issues) + 1:04d}"
    issues.append({"issue_id": issue_id, "severity": severity, "category": category, "message": message})


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _as_list(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []
