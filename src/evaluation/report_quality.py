"""Objective quality evaluation for generated company research reports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List

from src.data.canonical_metrics import canonical_metrics_as_financial_metrics
from src.agents.research_blackboard import quality_generalization_checks
from src.report.mojibake_guard import build_mojibake_quality_issue, looks_like_mojibake
from src.utils.config import load_config


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


def _resolve_quality_threshold(artifacts: Dict[str, Any]) -> float:
    """从 quality_gate.yaml 读取 market-specific 质量诊断阈值。

    解析逻辑：
      1. 从 run_summary.json 提取 symbol → 推断 market (cn_a/hk/us)
      2. 从 quality_gate.yaml 加载 market_overrides
      3. 如果有对应 market 的覆写值 → 使用覆写值
      4. 否则 → 使用 default (0.82)

    Returns:
        阈值 (float)，如 0.82, 0.60
    """
    summary = artifacts.get("summary", {}) or {}
    symbol = str(summary.get("symbol") or "").strip().upper()

    # 推断 market
    if symbol.endswith(".HK"):
        market = "hk"
    elif symbol.endswith((".SS", ".SZ")):
        market = "cn_a"
    elif symbol and "." not in symbol:
        market = "us"
    else:
        market = "unknown"

    # 从 quality_gate.yaml 加载阈值
    try:
        quality_config = load_config("configs/quality_gate.yaml")
        thresholds = quality_config.get("thresholds", {}) or {}
        default_threshold = float(thresholds.get("default", 0.82))
        overrides = thresholds.get("market_overrides", {}) or {}
        market_threshold = overrides.get(market)
        if market_threshold is not None:
            return float(market_threshold)
        return default_threshold
    except Exception:
        return 0.82  # 加载失败时回退到硬编码默认值


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
    _check_cross_market_regressions(artifacts, issues)
    _check_pdf_rag_policy(artifacts, issues)
    _check_final_html_artifact_policy(artifacts, issues)
    _check_cross_report_symbol_pollution(artifacts, issues)
    _check_peer_metric_contamination(artifacts, issues)
    _check_html_table_integrity(artifacts, issues)
    _check_developer_placeholder_leakage(artifacts, issues)
    _check_mojibake_policy(artifacts, issues)
    _check_claim_citation_policy(artifacts, issues)
    _check_evidence_identity_policy(artifacts, issues)
    _check_official_source_distribution_policy(artifacts, issues)
    _check_business_overview_wrong_section_policy(artifacts, issues)
    _valuation_consistency_check(artifacts, issues)
    generalization_checks = quality_generalization_checks(artifacts)
    _check_generalization_policy(generalization_checks, issues)
    # Contract-level checks (Phase 6)
    _check_contract_policies(artifacts, issues)
    total = round(sum(scores[key] * GROUP_WEIGHTS[key] for key in GROUP_WEIGHTS), 4)
    required = _required_gate_checks(artifacts, issues)
    fatal_count = sum(1 for issue in issues if issue["severity"] == "fatal")
    blocker_count = sum(1 for issue in issues if issue["severity"] == "blocker")
    quality_threshold = _resolve_quality_threshold(artifacts)
    objective_pass = bool(total >= quality_threshold and fatal_count == 0 and blocker_count == 0 and required["passed"])
    report = {
        "schema_version": "quality_report.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_dir": str(paths.run_dir),
        "outputs_dir": str(paths.outputs_dir),
        "reports_dir": str(paths.reports_dir),
        "total_score": total,
        "quality_threshold": quality_threshold,
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
        if not reports.exists():
            reports = _mirror_reports_dir(root)
        return RunPaths(run_dir=root.parent, outputs_dir=root, reports_dir=reports)
    if (root / "outputs").exists():
        return RunPaths(run_dir=root, outputs_dir=root / "outputs", reports_dir=root / "reports")
    reports = root.parent / "reports"
    if not reports.exists():
        reports = _mirror_reports_dir(root)
    return RunPaths(run_dir=root, outputs_dir=root, reports_dir=reports)


def _mirror_reports_dir(outputs_dir: Path) -> Path:
    parts = list(outputs_dir.parts)
    if "outputs_user" in parts:
        idx = parts.index("outputs_user")
        parts[idx] = "reports_user"
        if parts[-1] == "outputs":
            parts[-1] = "reports"
        return Path(*parts)
    if "outputs" in parts:
        idx = parts.index("outputs")
        parts[idx] = "reports"
        if parts[-1] == "outputs":
            parts[-1] = "reports"
        return Path(*parts)
    return outputs_dir.parent / "reports"


def load_quality_artifacts(paths: RunPaths) -> Dict[str, Any]:
    canonical_metrics = _read_json(paths.outputs_dir / "canonical_metrics.json", {})
    raw_financial_metrics = _read_json(paths.outputs_dir / "financial_metrics.json", {})
    financial_metrics = canonical_metrics_as_financial_metrics(canonical_metrics, fallback=raw_financial_metrics)
    return {
        "summary": _read_json(paths.outputs_dir / "run_summary.json", {}),
        "request_state": _read_json(paths.outputs_dir / "request_state.json", {}),
        "claims": _as_list(_read_json(paths.outputs_dir / "claims.json", [])),
        "evidence": _as_list(_read_json(paths.outputs_dir / "evidence.json", [])),
        "citations": _as_list(_read_json(paths.outputs_dir / "citations.json", [])),
        "tables": _as_list(_read_json(paths.outputs_dir / "tables.json", [])),
        "financial_metrics": financial_metrics,
        "canonical_metrics": canonical_metrics,
        "raw_financial_metrics": raw_financial_metrics,
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
        "analysis_artifacts": _read_json(paths.outputs_dir / "analysis_artifacts.json", {}),
        "section_dossiers": _read_json(paths.outputs_dir / "section_dossiers.json", {}),
        # Contract-first artifacts (optional — only present in contract-mode runs)
        "report_section_contracts": _read_json(paths.outputs_dir / "report_section_contracts.json", {}),
        "section_verification": _read_json(paths.outputs_dir / "section_verification.json", {}),
        "section_repair": _read_json(paths.outputs_dir / "section_repair.json", {}),
        "evidence_retrieval_attribution": _read_json(paths.outputs_dir / "evidence_retrieval_attribution.json", {}),
        "citation_map": _read_json(paths.outputs_dir / "citation_map.json", {}),
        "citation_binding_audit": _read_json(paths.outputs_dir / "citation_binding_audit.json", {}),
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
    visible_text = _strip_reference_sections(str(artifacts.get("report_md") or text))
    statements = _statement_names_from_tables(tables)
    has_income = any("income" in item for item in statements)
    has_balance = any("balance" in item for item in statements)
    has_cashflow = any("cash" in item for item in statements) or _has_cashflow_gap_explained(text)
    for ok, name in [(has_income, "income"), (has_balance, "balance"), (has_cashflow, "cashflow")]:
        if not ok:
            _issue(issues, "blocker", "financial", f"missing {name} summary")
    if SCI_NOTATION_RE.search(visible_text):
        _issue(issues, "blocker", "financial", "report contains scientific notation, unprofessional financial display")
    if not re.search(r"(billion|million|pct|bps|%)", text, flags=re.IGNORECASE):
        _issue(issues, "warning", "financial", "report lacks clear unit or percentage expression")
    if re.search(r"0700\.HK|Tencent|腾讯", text, re.I) and re.search(r"751,?766,?000,?000\s+USD|751\.?766\s+billion\s+USD", text, re.I):
        _issue(issues, "blocker", "currency_unit_mismatch", "Tencent RMB financial statement amount is labeled USD")
    metric_score = 1.0 if metrics else 0.45
    period_alignment = _period_alignment_score(artifacts, issues)
    table_score = (int(has_income) + int(has_balance) + int(has_cashflow)) / 3
    return round(0.45 * table_score + 0.25 * metric_score + 0.2 * period_alignment + 0.1 * (0 if SCI_NOTATION_RE.search(visible_text) else 1), 4)


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
    "valuation": 160,
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
    "本节暂不展开详细分析",
    "evidence_not_available",
    "valuation_sensitivity_not_available",
    "持续深耕",
    "巩固核心竞争力",
]

HALF_SENTENCE_MARKERS = [
    "half_sentence",
    "incomplete",
    "needs_attention",
]

HALF_SENTENCE_REGEXES = [
    r"(?:与|及|和|并|或|、|：|，|,)\s*$",
    r"(?:本报告|本节|公司|风险|估值|结论)[^。\n]{8,80}(?:与|及|和|并|或|、|：|，|,)\s*$",
    r"(?:分别披露|主要包括|主要来自|体现为|取决于)[^。\n]{0,80}$",
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
    """Check every core section against the formal delivery section contract."""
    section_dossiers = artifacts.get("section_dossiers", {})
    if not isinstance(section_dossiers, dict):
        section_dossiers = {}
    text = _report_text(artifacts)
    body_text = _strip_reference_sections(str(artifacts.get("report_md") or text))
    total_checks = len(CONTENT_DEPTH_THRESHOLDS)
    passes = 0

    for section_key, threshold in CONTENT_DEPTH_THRESHOLDS.items():
        heading = SECTION_HEADING_MAP.get(section_key, "")
        if not heading:
            continue
        body = _section_body(text, (heading,))
        if not body:
            _issue(issues, "blocker", "content_depth", f"{heading} section missing")
            continue
        chinese_chars = len(re.sub(r"[\s\n\r#\-*:：，、。）（\[\]【】\"''a-zA-Z0-9]", "", body))
        if chinese_chars >= threshold:
            if not _section_has_truncation(body):
                passes += 1
                continue
        dossier = section_dossiers.get(section_key, {})
        if isinstance(dossier, dict) and dossier.get("min_content_level") == "data_gap":
            passes += 1
            continue
        if chinese_chars < threshold:
            _issue(
                issues,
                "blocker",
                "content_depth",
                f"{heading} content insufficient: only {chinese_chars} chars (threshold {threshold})",
            )
        if _section_has_truncation(body):
            _issue(issues, "blocker", "content_depth", f"{heading} appears truncated or ends with an unfinished phrase")

    # Template phrase detection
    for phrase in TEMPLATE_PHRASES:
        if phrase in body_text:
            _issue(issues, "blocker", "content_depth", f"report contains template phrase: {phrase}")

    # Half-sentence detection
    for marker in HALF_SENTENCE_MARKERS:
        if marker in body_text:
            _issue(issues, "blocker", "content_depth", f"report contains half-sentence marker: {marker}")
    sentence_check_text = _without_structural_list_labels(body_text)
    for pattern in HALF_SENTENCE_REGEXES:
        if re.search(pattern, sentence_check_text.strip(), flags=re.MULTILINE):
            _issue(issues, "blocker", "content_depth", f"report contains unfinished sentence pattern: {pattern}")

    # Debug/internal ID leakage detection
    for pattern in DEBUG_LEAK_PATTERNS:
        if pattern in text:
            _issue(issues, "blocker", "content_depth", f"report contains debug leakage: {pattern}")
    if _contains_any(body_text, ("Item 1A", "Risk Factors", "Management's Discussion", "Our business", "We face intense competition")) and len(re.findall(r"\b[A-Za-z]{5,}\b", body_text)) > 120:
        _issue(issues, "blocker", "raw_english_annual_section_leak", "report appears to contain raw English annual-report sections")
    report_body_text = _strip_reference_sections(
        "\n".join([str(artifacts.get("report_md") or ""), str(artifacts.get("report_html") or "")])
    )
    for key in ("revenue_growth_pct", "adjusted_net_income", "non_recurring_gain"):
        if key in report_body_text:
            _issue(issues, "blocker", "internal_metric_key_leak", f"internal metric key leaked: {key}")

    # Raw SEC companyfacts dump detection
    for pat in COMPANYFACTS_DUMP_PATTERNS_RE:
        if re.search(pat, body_text):
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


def _strip_reference_sections(text: str) -> str:
    """Keep citation metadata out of prose-quality and raw-English checks."""
    value = str(text or "")
    match = re.search(r"(?im)^##\s+(?:参考来源|References)\s*$", value)
    return value[: match.start()] if match else value


def _section_has_truncation(body: str) -> bool:
    lines = [line.strip() for line in str(body or "").splitlines() if line.strip()]
    if not lines:
        return False
    tail = lines[-1]
    if tail.startswith("|"):
        return False
    if tail.endswith(("。", "！", "？", ".", "!", "?", "）", ")", "]", "】")):
        return False
    return bool(re.search(r"(?:与|及|和|并|或|、|：|，|,)$", tail) or len(tail) >= 12)


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


def _without_structural_list_labels(text: str) -> str:
    lines = str(text or "").splitlines()
    output: List[str] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.endswith(("：", ":")) or len(stripped) > 80:
            output.append(line)
            continue
        next_line = next((item.strip() for item in lines[index + 1 :] if item.strip()), "")
        if next_line.startswith(("-", "*", "|")) or next_line.endswith(("：", ":")):
            continue
        output.append(line)
    return "\n".join(output)


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
    resolved_symbol = _expected_symbol(artifacts)
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
    if evidence_coverage.get("formal_delivery_allowed") is False or evidence_coverage.get("degrade_required") is True:
        reasons = evidence_coverage.get("blocking_reasons")
        if not isinstance(reasons, list) or not reasons:
            reasons = evidence_coverage.get("missing_requirements", [])
        missing = ", ".join(str(item) for item in reasons[:6]) if isinstance(reasons, list) else str(reasons)
        _issue(
            issues,
            "blocker",
            "official_evidence",
            f"Official evidence is insufficient for formal delivery; generate draft only until fixed: {missing}",
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

    # Check for CNY strings in USD report deliverables
    _check_currency_market_mismatch(artifacts, issues, market, symbol)


def _check_cross_market_regressions(
    artifacts: Dict[str, Any],
    issues: List[Dict[str, Any]],
) -> None:
    search_meta = artifacts.get("search_meta", {}) if isinstance(artifacts.get("search_meta"), dict) else {}
    engine_meta = search_meta.get("engine_meta", {}) if isinstance(search_meta.get("engine_meta"), dict) else {}
    local_meta = engine_meta.get("local_evidence", {}) if isinstance(engine_meta.get("local_evidence"), dict) else {}
    if (
        str(local_meta.get("mode") or "") in {"vector", "hybrid", "hybrid_rerank"}
        and int(local_meta.get("source_record_count") or 0) == 0
        and str(local_meta.get("mode_effective") or "") != "unavailable"
    ):
        severity = "warning" if _artifact_has_evidence_records(artifacts) else "blocker"
        _issue(
            issues,
            severity,
            "retrieval_unavailable_misreported",
            "local retrieval reports a vector/hybrid mode although no candidate records were loaded",
        )

    contracts = artifacts.get("report_section_contracts", {})
    contracts_data = contracts.get("contracts", {}) if isinstance(contracts, dict) else {}
    peer = contracts_data.get("peer_compare", {}) if isinstance(contracts_data, dict) else {}
    if isinstance(peer, dict) and str(peer.get("status") or "") == "supported":
        text = str(peer.get("deterministic_text") or "")
        report_peer_body = _section_body(_report_text(artifacts), ("同行对比", "同行比较", "peer_compare", "peer comparison"))
        boundary_disclosed = _contains_any(
            report_peer_body,
            (
                "没有完整同业样本",
                "同业样本不足",
                "不输出绝对强弱排序",
                "保留审慎比较口径",
                "补齐同行",
                "peer data gap",
            ),
        )
        rows = [line for line in text.splitlines() if line.startswith("|")][2:]
        populated = [
            line for line in rows
            if any(token.strip() for token in line.split("|")[3:7])
            and "目标公司" not in line
        ]
        if not populated and not boundary_disclosed:
            _issue(issues, "blocker", "peer_supported_without_metrics", "peer comparison is supported without a populated non-target peer row")

    summary = artifacts.get("summary", {}) if isinstance(artifacts.get("summary"), dict) else {}
    symbol = str(summary.get("symbol") or "").upper()
    market = str((artifacts.get("currency_audit") or {}).get("market") or "")
    if not market and symbol and not symbol.endswith((".SS", ".SZ", ".HK")):
        market = "us"
    if market == "us":
        governance = _section_body(_report_text(artifacts), ("股权结构与公司治理", "公司治理", "governance"))
        if "监事会" in governance:
            _issue(issues, "blocker", "us_governance_market_mismatch", "US governance section contains A-share supervisory-board terminology")

    sensitivity = artifacts.get("valuation_sensitivity", {}) if isinstance(artifacts.get("valuation_sensitivity"), dict) else {}
    has_scenarios = isinstance(sensitivity.get("scenario_values"), dict) and len(sensitivity["scenario_values"]) >= 2
    sensitivity_contract = contracts_data.get("valuation_sensitivity", {}) if isinstance(contracts_data, dict) else {}
    if has_scenarios and isinstance(sensitivity_contract, dict) and str(sensitivity_contract.get("status") or "") == "gap":
        _issue(issues, "blocker", "valuation_sensitivity_dropped", "valuation sensitivity scenarios exist but the report contract marks the section as gap")


def _check_currency_market_mismatch(
    artifacts: Dict[str, Any],
    issues: List[Dict[str, Any]],
    market: str,
    symbol: str,
) -> None:
    """Check that USD report deliverables (report.html, report.md) don't contain
    Chinese currency strings (人民币, 亿元/万亿元, CNY as unit).

    Report language being Chinese does NOT mean currency units should be CNY
    for a USD-reporting company.
    """
    # Determine report_currency from currency_audit
    audit = artifacts.get("currency_audit", {}) if isinstance(artifacts.get("currency_audit"), dict) else {}
    report_currency = str(audit.get("statement_currency") or audit.get("trading_currency") or "USD").upper()
    # For US companies without explicit audit, default is USD
    if market == "us" and report_currency in ("", "UNKNOWN"):
        report_currency = "USD"

    if report_currency != "USD":
        return  # only check USD reports

    # Scan report text for CNY currency strings
    text = _report_text(artifacts)
    if not text or len(text) < 50:
        return

    # Chinese currency unit patterns that should NOT appear in USD reports
    # Note: "亿美元" = hundred million USD (legitimate), "亿元人民币" = RMB (illegitimate)
    cny_patterns = [
        r'人民币',
        # "亿" followed by CNY unit; NOT standalone "亿" (which would match "亿美元")
        r'(?<!\d)(\d+[\s,]*)?亿元',
        r'(?<!\d)(\d+[\s,]*)?亿人民币',
        r'(?<!\d)\d+[\s,]*万亿元',
        r'(?<!\d)\d+[\s,]*万(?:元|人民币)',
    ]
    # Also check for "CNY" used as a currency unit (not as a ticker/symbol reference)
    # and "RMB" as a display currency
    cny_ref_patterns = [
        r'\bCNY\b',
        r'\bRMB\b',
    ]

    found_cny: List[str] = []
    for pattern in cny_patterns:
        matches = re.findall(pattern, text)
        if matches:
            found_cny.append(pattern)

    # For CNY/RMB references, be more careful - check they're used as currency
    # and not as part of a ticker or example
    for pattern in cny_ref_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            found_cny.append(pattern)

    if found_cny:
        # Check severity: 亿/万亿+数字 is more serious than just CNY reference
        has_amount = any('亿' in p or '万亿' in p or '万' in p for p in found_cny)
        severity = "blocker" if has_amount else "warning"
        _issue(
            issues,
            severity,
            "currency_market_mismatch",
            f"{symbol} report_currency=USD but contains CNY currency strings: {', '.join(found_cny[:5])}",
        )


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
    for summary in summaries:
        if not isinstance(summary, dict):
            continue
        summary_text = str(summary.get("summary_zh") or "")
        section_type = str(summary.get("section_type") or "unknown")
        if summary.get("usable_for_generation") and _contains_mojibake(summary_text):
            _issue(issues, "blocker", "pdf_rag", f"usable PDF summary contains mojibake: {section_type}")
        if summary.get("usable_for_generation") and _looks_like_raw_pdf_summary(summary_text):
            _issue(issues, "blocker", "pdf_rag", f"usable PDF summary is raw/overlong instead of compressed: {section_type}")


def _check_final_html_artifact_policy(artifacts: Dict[str, Any], issues: List[Dict[str, Any]]) -> None:
    report_html = str(artifacts.get("report_html") or "")
    if not report_html.strip():
        _issue(issues, "fatal", "html_artifact", "final report.html is empty")
        return
    if "<html" not in report_html.lower():
        _issue(issues, "blocker", "html_artifact", "final report.html is not a complete html artifact")


def _check_cross_report_symbol_pollution(artifacts: Dict[str, Any], issues: List[Dict[str, Any]]) -> None:
    report_html = str(artifacts.get("report_html") or "")
    if not report_html:
        return
    expected_symbol = _expected_symbol(artifacts)
    approved_peers = _approved_peer_symbols(artifacts)
    approved = {expected_symbol} if expected_symbol else set()
    if expected_symbol and expected_symbol.startswith("0"):
        approved.add(expected_symbol.replace(".HK", ""))
    report_body_html = _report_main_html(report_html)
    peer_html, non_peer_html = _split_peer_section_html(report_body_html)
    matches = _ticker_like_symbols(report_body_html)
    peer_matches = _ticker_like_symbols(peer_html)
    non_peer_matches = _ticker_like_symbols(non_peer_html)
    currency_tokens = {"USD", "CNY", "RMB", "HKD", "JPY", "EUR", "GBP", "AUD", "CAD", "CHF"}
    cleaned = {str(match).strip().upper() for match in matches if str(match).strip() and str(match).strip().upper() not in currency_tokens}
    allowed_in_peer = approved | approved_peers
    unexpected = sorted(
        symbol for symbol in cleaned
        if symbol and (
            symbol not in allowed_in_peer
            or (symbol in approved_peers and symbol in non_peer_matches)
            or (symbol in approved_peers and symbol not in peer_matches)
        )
    )
    if unexpected:
        _issue(issues, "blocker", "cross_report_symbol_pollution", f"unexpected ticker-like symbols in final html: {unexpected[:8]}")


def _ticker_like_symbols(text: str) -> set[str]:
    matches = set(re.findall(r"\b\d{4}\.HK\b|\b\d{6}\.(?:SS|SZ)\b", str(text or "")))
    matches.update(re.findall(r"\(([A-Z]{1,6})\)", str(text or "")))
    return {str(match).strip().upper() for match in matches if str(match).strip()}


def _report_main_html(report_html: str) -> str:
    match = re.search(r"<main\b[^>]*>(.*?)</main>", str(report_html or ""), flags=re.I | re.S)
    return match.group(1) if match else str(report_html or "")


def _split_peer_section_html(report_html: str) -> tuple[str, str]:
    pattern = re.compile(
        r"(<h2\b[^>]*>(?:(?!</h2>).)*(?:同行对比|Peer Comparison|Peer Compare)(?:(?!</h2>).)*</h2>)(.*?)(?=<h2\b|</body>|</html>|\Z)",
        flags=re.I | re.S,
    )
    matches = list(pattern.finditer(str(report_html or "")))
    peer_html = "\n".join(match.group(0) for match in matches)
    non_peer_html = str(report_html or "")
    for match in reversed(matches):
        non_peer_html = non_peer_html[: match.start()] + non_peer_html[match.end() :]
    return peer_html, non_peer_html


def _check_evidence_identity_policy(artifacts: Dict[str, Any], issues: List[Dict[str, Any]]) -> None:
    expected_symbol = _expected_symbol(artifacts)
    if not expected_symbol:
        return
    expected_terms = _identity_terms_for_symbol(expected_symbol, artifacts)
    if not expected_terms:
        return
    polluted: list[str] = []
    evidence_records = [record for record in artifacts.get("evidence", []) if isinstance(record, dict)]
    evidence_by_id = {
        str(record.get("evidence_id") or record.get("sample_id") or ""): record
        for record in evidence_records
        if str(record.get("evidence_id") or record.get("sample_id") or "")
    }
    for record in evidence_records:
        if not isinstance(record, dict):
            continue
        evidence_id = str(record.get("evidence_id") or record.get("sample_id") or "")
        source_type = str(record.get("source_type") or "").lower()
        if source_type not in {"hkex_announcement", "cninfo_announcement", "exchange_announcement", "pdf_section"}:
            continue
        text = " ".join(
            [
                str(record.get("title") or ""),
                str(record.get("content") or ""),
                str(record.get("source_url") or ""),
            ]
        ).lower()
        if not text.strip():
            continue
        if source_type == "pdf_section":
            if _pdf_lineage_matches_identity(
                record,
                evidence_by_id,
                expected_symbol=expected_symbol,
                expected_period=_expected_period(artifacts),
                expected_terms=expected_terms,
            ):
                continue
        elif any(term in text for term in expected_terms):
            continue
        polluted.append(evidence_id or str(record.get("title") or source_type))
    if polluted:
        _issue(
            issues,
            "fatal",
            "evidence_identity_pollution",
            f"official/pdf evidence does not mention target company {expected_symbol}: {polluted[:5]}",
        )


def _pdf_lineage_matches_identity(
    record: Dict[str, Any],
    evidence_by_id: Dict[str, Dict[str, Any]],
    *,
    expected_symbol: str,
    expected_period: str,
    expected_terms: set[str],
    max_depth: int = 8,
) -> bool:
    if str(record.get("source_type") or "").lower() != "pdf_section":
        return False
    current = record
    visited: set[str] = set()
    for _depth in range(max_depth + 1):
        current_id = str(current.get("evidence_id") or current.get("sample_id") or "")
        if current_id:
            if current_id in visited:
                return False
            visited.add(current_id)
        metadata = current.get("metadata") if isinstance(current.get("metadata"), dict) else {}
        parent_id = str(metadata.get("source_evidence_id") or "")
        if not parent_id or parent_id == current_id:
            return _official_identity_terminal_matches(
                current,
                expected_symbol=expected_symbol,
                expected_period=expected_period,
                expected_terms=expected_terms,
            )
        parent = evidence_by_id.get(parent_id)
        if not isinstance(parent, dict):
            return False
        current = parent
    return False


def _official_identity_terminal_matches(
    record: Dict[str, Any], *, expected_symbol: str, expected_period: str, expected_terms: set[str]
) -> bool:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    declared_symbol = str(record.get("symbol") or metadata.get("expected_symbol") or "").strip().upper()
    declared_period = str(record.get("period") or metadata.get("target_period") or metadata.get("period") or "").strip().upper()
    if declared_symbol != expected_symbol.upper():
        return False
    if expected_period and declared_period != expected_period.upper():
        return False
    source_type = str(record.get("source_type") or "").strip().lower()
    document_type = str(record.get("source_document_type") or "").strip().lower()
    authority = str(record.get("source_authority") or "").strip().lower()
    url = str(record.get("source_url") or "").strip().lower()
    official_types = {"cninfo_announcement", "exchange_announcement", "hkex_announcement", "official_filing"}
    official_domains = ("cninfo.com.cn", "sse.com.cn", "szse.cn", "hkexnews.hk")
    if source_type not in official_types and document_type not in official_types and authority != "official" and not any(domain in url for domain in official_domains):
        return False
    text = " ".join([str(record.get("title") or ""), str(record.get("content") or ""), url]).lower()
    role = str(metadata.get("evidence_role") or "").strip().lower()
    expected = str(metadata.get("expected_symbol") or "").strip().upper()
    return any(term in text for term in expected_terms) or (role == "target" and expected == expected_symbol.upper())


def _identity_terms_for_symbol(symbol: str, artifacts: Dict[str, Any]) -> set[str]:
    symbol_text = str(symbol or "").strip().lower()
    terms = {symbol_text}
    if "." in symbol_text:
        terms.add(symbol_text.split(".", 1)[0].lstrip("0") or symbol_text.split(".", 1)[0])
    summary = artifacts.get("summary", {}) if isinstance(artifacts.get("summary"), dict) else {}
    entity = summary.get("entity_resolution", {}) if isinstance(summary.get("entity_resolution"), dict) else {}
    for raw in [entity.get("company_name"), entity.get("resolved_name")]:
        name = str(raw or "").strip().lower()
        if not name:
            continue
        terms.add(name)
        simplified = re.sub(r"\b(holdings|holding|limited|ltd|inc|corp|corporation|company|co)\b\.?", "", name, flags=re.I)
        simplified = " ".join(simplified.split())
        if len(simplified) >= 4:
            terms.add(simplified)
        for token in re.split(r"[^a-z0-9]+", name):
            if len(token) >= 5:
                terms.add(token)
    try:
        from src.app.company_aliases import RAW_COMPANY_ENTRIES

        for entry in RAW_COMPANY_ENTRIES:
            if str(entry.get("symbol") or "").strip().lower() != symbol_text:
                continue
            terms.add(str(entry.get("company_name") or "").strip().lower())
            terms.update(str(alias or "").strip().lower() for alias in entry.get("aliases", []))
    except (ImportError, TypeError):
        pass
    return {term for term in terms if len(term) >= 3}


def _check_peer_metric_contamination(artifacts: Dict[str, Any], issues: List[Dict[str, Any]]) -> None:
    text = _section_body(_report_text(artifacts), ("同行对比", "peer compare", "Peer Comparison"))
    if not text:
        return
    metric_terms = ("收入增速", "毛利率", "净利率", "ROE")
    if sum(1 for term in metric_terms if term in text) < 3:
        return
    if re.search(r"6\.5\s*[;%；].*90\.51\s*[;%；].*48\.05\s*[;%；].*31\.2", text, re.S):
        _issue(issues, "blocker", "peer_metric_contamination", "orphan peer metric row remains without an approved peer symbol")


def _check_html_table_integrity(artifacts: Dict[str, Any], issues: List[Dict[str, Any]]) -> None:
    report_html = str(artifacts.get("report_html") or "")
    if not report_html:
        return
    if "&lt;table" in report_html.lower() or "&lt;thead" in report_html.lower() or "&lt;tbody" in report_html.lower():
        _issue(issues, "blocker", "html_table_integrity", "final html contains escaped table markup")
    if re.search(r"(?m)^\|.*\|$", report_html) or "| --- |" in report_html or "| ---: |" in report_html or "<th>---</th>" in report_html or "<th>---:</th>" in report_html:
        _issue(issues, "blocker", "html_table_integrity", "final html still contains markdown table residue")
    if re.search(r"<ul>\s*<table", report_html, re.I):
        _issue(issues, "blocker", "html_table_integrity", "final html nests table directly inside ul")
    if "<table" in report_html.lower() and "<th" not in report_html.lower():
        _issue(issues, "blocker", "html_table_integrity", "final html table is missing header cells")
    if re.search(r"<th>\s*</th>", report_html, re.I):
        _issue(issues, "blocker", "html_table_integrity", "final html contains empty table headers")


def _check_developer_placeholder_leakage(artifacts: Dict[str, Any], issues: List[Dict[str, Any]]) -> None:
    text = _report_text(artifacts)
    patterns = [
        "TODO",
        "FIXME",
        "developer placeholder",
        "正文应使用中文归纳",
        "章节已抽取",
        "section extracted",
    ]
    for pattern in patterns:
        if pattern in text:
            _issue(issues, "blocker", "developer_placeholder", f"developer placeholder leaked to final artifact: {pattern}")


def _check_mojibake_policy(artifacts: Dict[str, Any], issues: List[Dict[str, Any]]) -> None:
    report_html = str(artifacts.get("report_html") or "")
    mojibake_patterns = [
        r"\uFFFD",
        r"鈹",
        r"璇佹嵁",
        r"缁撹",
        r"鎬",
        r"鐠",
        r"缂",
        r"閹",
        r"锟",
        r"Ã",
        r"Â",
    ]
    for pattern in mojibake_patterns:
        if re.search(pattern, report_html):
            _issue(issues, "blocker", "mojibake_policy", f"mojibake detected in final html: {pattern}")
            break


def _contains_mojibake(text: str) -> bool:
    patterns = [
        r"\uFFFD",
        r"鈥|鈭|鈻|鈹",
        r"璐靛|璇佹|缁撹|鎽樿|鐩",
        r"鍏|涓氬|锛",
        r"[ÃÂ]",
    ]
    return any(re.search(pattern, str(text or "")) for pattern in patterns)


def _looks_like_raw_pdf_summary(text: str) -> bool:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(value) <= 700:
        return False
    sentence_count = len(re.findall(r"[。！？.!?]", value))
    return sentence_count < 3 or len(value) > 1200


def _check_official_source_distribution_policy(artifacts: Dict[str, Any], issues: List[Dict[str, Any]]) -> None:
    official_manifest = json.dumps(artifacts.get("official_evidence_manifest", {}), ensure_ascii=False)
    evidence_coverage = json.dumps(artifacts.get("evidence_coverage", {}), ensure_ascii=False)
    joined = f"{official_manifest}\n{evidence_coverage}"
    if re.search(r"eastmoney", joined, re.I) and re.search(r"official|primary", joined, re.I):
        _issue(issues, "blocker", "official_source_distribution", "Eastmoney is counted as official/primary source")


def _check_business_overview_wrong_section_policy(artifacts: Dict[str, Any], issues: List[Dict[str, Any]]) -> None:
    text = _report_text(artifacts)
    business_body = _section_body(text, ("业务概览", "business overview", "主营业务与业务画像"))
    if any(marker in business_body for marker in ["财务费用变动原因说明", "经营活动产生的现金流量净额变动原因说明", "投资活动产生的现金流量净额变动原因说明", "筹资活动产生的现金流量净额变动原因说明"]):
        _issue(issues, "blocker", "business_overview_wrong_section", "business_overview appears to contain financial-note variance text")
    audit = artifacts.get("pdf_extraction_audit", {}) if isinstance(artifacts.get("pdf_extraction_audit"), dict) else {}
    summaries = artifacts.get("pdf_section_summaries", []) if isinstance(artifacts.get("pdf_section_summaries"), list) else []
    has_usable_pdf_summary = bool(audit.get("page_count")) and any(bool(item.get("usable_for_generation")) for item in summaries if isinstance(item, dict))
    if has_usable_pdf_summary and any(marker in text for marker in ["未获得官方证据", "未获得足够的官方治理结构证据", "尚未获得可直接支持分析的官方章节摘要"]):
        _issue(issues, "blocker", "business_overview_wrong_section", "official PDF summary exists but report still claims no official evidence")


def _check_contract_policies(artifacts: Dict[str, Any], issues: List[Dict[str, Any]]) -> None:
    """Run contract-level checks on report_section_contracts.json.

    These checks detect violations that the contract system is designed to prevent:
    - PDF boilerplate in business_overview
    - governance gap despite PDF availability
    - citation binding mismatch
    - peer universe mismatch
    - period metadata missing
    - sentence fragments
    - stale runtime source leak
    """
    contracts = artifacts.get("report_section_contracts", {})
    has_contracts = isinstance(contracts, dict) and contracts.get("contracts") is not None
    binding_audit = artifacts.get("citation_binding_audit", {})
    has_audit = isinstance(binding_audit, dict) and bool(binding_audit)

    if not has_contracts and not has_audit:
        # Contract-first mode not active — skip
        return

    report_md = str(artifacts.get("report_md", ""))
    contracts_data = contracts.get("contracts", {}) if isinstance(contracts, dict) else {}

    # 1. business_overview_raw_pdf_paste
    biz = contracts_data.get("business_overview", {})
    if isinstance(biz, dict):
        biz_facts = biz.get("facts", []) if isinstance(biz.get("facts"), list) else []
        for fact in biz_facts:
            if isinstance(fact, dict):
                ft = str(fact.get("text", ""))
                if "年度报告" in ft or "四、" in ft or "五、" in ft or "√适用" in ft:
                    _issue(issues, "blocker", "business_overview_raw_pdf_paste",
                           "business_overview fact contains PDF formatting boilerplate")
                    break
        for qf in (biz.get("quality_flags", []) if isinstance(biz.get("quality_flags"), list) else []):
            if "boilerplate" in str(qf):
                _issue(issues, "warning", "business_overview_raw_pdf_paste",
                       f"business_overview quality flag: {qf}")

    # 2. governance_gap
    gov = contracts_data.get("ownership_governance", {})
    if isinstance(gov, dict):
        gov_status = str(gov.get("status", ""))
        pdf_rag_available = bool(contracts.get("metadata", {}).get("pdf_rag_available", False))
        if pdf_rag_available and gov_status == "gap":
            blocked = [str(r) for r in (gov.get("blocked_reasons", []) if isinstance(gov.get("blocked_reasons"), list) else [])]
            reason = blocked[0] if blocked else "governance_section_not_found"
            _issue(issues, "blocker", "governance_gap",
                   f"ownership_governance is gap despite PDF available: {reason}")

    # 3. citation_binding_mismatch
    if binding_audit.get("total_mismatches", 0) > 0:
        mismatches = binding_audit.get("mismatches", [])[:3]
        _issue(issues, "blocker", "citation_binding_mismatch",
               f"citation binding has {binding_audit['total_mismatches']} mismatches: {'; '.join(mismatches)}")
    for sk, cdata in contracts_data.items():
        if isinstance(cdata, dict):
            for qf in (cdata.get("quality_flags", []) if isinstance(cdata.get("quality_flags"), list) else []):
                if "citation_binding_mismatch" in str(qf):
                    _issue(issues, "warning", "citation_binding_mismatch",
                           f"{sk}: {qf}")

    # 4. peer_universe_mismatch
    peer = contracts_data.get("peer_compare", {})
    if isinstance(peer, dict):
        for qf in (peer.get("quality_flags", []) if isinstance(peer.get("quality_flags"), list) else []):
            if "peer_universe" in str(qf):
                _issue(issues, "warning", "peer_universe_mismatch",
                       f"peer_compare: {qf}")
        if any(term in report_md for term in ["PG/KO/PEP/WMT/COST", "同一行业或业务相近口径"]):
            _issue(issues, "blocker", "peer_universe_mismatch",
                   "report lists foreign peers as same-industry comparables")

    # 5. period_metadata_missing
    period_note = contracts_data.get("period_note", {})
    if isinstance(period_note, dict):
        pn_status = str(period_note.get("status", ""))
        if pn_status == "gap":
            _issue(issues, "blocker", "period_metadata_missing",
                   "period_note contract is gap — latest_available_period not detected")
        for qf in (period_note.get("quality_flags", []) if isinstance(period_note.get("quality_flags"), list) else []):
            if "period_mismatch" in str(qf):
                _issue(issues, "warning", "period_metadata_missing",
                       "period mismatch detected between target and available periods")

    # 6. sentence_fragment
    for sk, cdata in contracts_data.items():
        if isinstance(cdata, dict):
            for qf in (cdata.get("quality_flags", []) if isinstance(cdata.get("quality_flags"), list) else []):
                qf_str = str(qf)
                if "fragment" in qf_str:
                    _issue(issues, "warning", "sentence_fragment",
                           f"{sk}: contains fragment patterns: {qf_str}")

    # 7. stale_runtime_source_leak
    for sk, cdata in contracts_data.items():
        if isinstance(cdata, dict):
            for qf in (cdata.get("quality_flags", []) if isinstance(cdata.get("quality_flags"), list) else []):
                if "risk_fallback_cashflow" in str(qf):
                    _issue(issues, "blocker", "stale_runtime_source_leak",
                           f"{sk}: {qf}")


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


def _artifact_has_evidence_records(artifacts: Dict[str, Any]) -> bool:
    evidence = artifacts.get("evidence")
    if isinstance(evidence, list) and any(isinstance(item, dict) for item in evidence):
        return True
    claims = artifacts.get("claims")
    if isinstance(claims, list):
        return any(isinstance(item, dict) and item.get("evidence_ids") for item in claims)
    return False


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


def _expected_symbol(artifacts: Dict[str, Any]) -> str:
    summary = artifacts.get("summary", {}) if isinstance(artifacts.get("summary"), dict) else {}
    entity = summary.get("entity_resolution", {}) if isinstance(summary.get("entity_resolution"), dict) else {}
    request_state = artifacts.get("request_state", {}) if isinstance(artifacts.get("request_state"), dict) else {}
    report_json = artifacts.get("report_json", {}) if isinstance(artifacts.get("report_json"), dict) else {}
    company_identity = request_state.get("company_identity", {}) if isinstance(request_state.get("company_identity"), dict) else {}
    return str(
        entity.get("resolved_symbol")
        or summary.get("symbol")
        or request_state.get("symbol")
        or company_identity.get("symbol")
        or report_json.get("symbol")
        or ""
    ).strip().upper()


def _expected_period(artifacts: Dict[str, Any]) -> str:
    summary = artifacts.get("summary", {}) if isinstance(artifacts.get("summary"), dict) else {}
    request_state = artifacts.get("request_state", {}) if isinstance(artifacts.get("request_state"), dict) else {}
    report_json = artifacts.get("report_json", {}) if isinstance(artifacts.get("report_json"), dict) else {}
    return str(summary.get("period") or request_state.get("period") or report_json.get("period") or "").strip().upper()


def _approved_peer_symbols(artifacts: Dict[str, Any]) -> set[str]:
    approved: set[str] = set()
    analysis = artifacts.get("analysis_artifacts", {}) if isinstance(artifacts.get("analysis_artifacts"), dict) else {}
    peer_analysis = analysis.get("peer_analysis", {}) if isinstance(analysis.get("peer_analysis"), dict) else {}
    peer_context = analysis.get("peer_context", {}) if isinstance(analysis.get("peer_context"), dict) else {}
    for source in (peer_analysis, peer_context, analysis):
        for value in source.get("approved_peer_symbols", []) if isinstance(source.get("approved_peer_symbols"), list) else []:
            symbol = str(value or "").strip().upper()
            if symbol:
                approved.add(symbol)
        for row in source.get("peer_rows", []) if isinstance(source.get("peer_rows"), list) else []:
            if isinstance(row, dict) and not bool(row.get("is_target")):
                symbol = str(row.get("symbol") or row.get("ticker") or "").strip().upper()
                if symbol:
                    approved.add(symbol)
    section_dossiers = artifacts.get("section_dossiers", {}) if isinstance(artifacts.get("section_dossiers"), dict) else {}
    peer = section_dossiers.get("peer_compare", {}) if isinstance(section_dossiers.get("peer_compare"), dict) else {}
    for table in peer.get("tables", []) if isinstance(peer.get("tables"), list) else []:
        rows = table.get("rows", []) if isinstance(table, dict) else []
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict):
                symbol = str(row.get("symbol") or row.get("ticker") or "").strip().upper()
                if symbol:
                    approved.add(symbol)
    return approved


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
    body = _section_body(text, ("investment_conclusion", "recommendation", "rating", "投资结论", "投资建议", "评级"))
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
    fy_mismatches = _fy_end_date_mismatches(artifacts, summary_period)
    if fy_mismatches:
        _issue(
            issues,
            "blocker",
            "source_period_mismatch",
            f"target fiscal period {summary_period} conflicts with source end dates: {fy_mismatches[:5]}",
        )
        return 0.45
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


def _fy_end_date_mismatches(artifacts: Dict[str, Any], summary_period: str) -> list[str]:
    match = re.fullmatch(r"FY(20\d{2})", str(summary_period or "").upper())
    if not match:
        return []
    target_year = int(match.group(1))
    mismatches: list[str] = []
    for source_name, item in _iter_period_records(artifacts):
        end_date = _record_end_date(item)
        if not end_date:
            continue
        if _record_has_fiscal_alias(item, summary_period):
            continue
        if end_date[:4].isdigit() and int(end_date[:4]) != target_year:
            label = str(item.get("evidence_id") or item.get("source_evidence_id") or item.get("table_id") or source_name)
            mismatches.append(f"{label}:{end_date}")
    return list(dict.fromkeys(mismatches))


def _iter_period_records(artifacts: Dict[str, Any]):
    for key in ["evidence", "tables"]:
        for item in artifacts.get(key, []):
            if not isinstance(item, dict):
                continue
            yield key, item
            rows = item.get("rows")
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, dict):
                        yield key, row
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            financials = metadata.get("financials") if isinstance(metadata.get("financials"), dict) else {}
            for nested_key in ["income_history", "balance_history", "cashflow_history", "cash_flow_history"]:
                rows = financials.get(nested_key)
                if isinstance(rows, list):
                    for row in rows:
                        if isinstance(row, dict):
                            yield f"{key}.{nested_key}", row
    metrics = artifacts.get("financial_metrics", {})
    metric_rows = metrics if isinstance(metrics, list) else metrics.get("metrics", []) if isinstance(metrics, dict) else []
    if isinstance(metric_rows, list):
        for item in metric_rows:
            if isinstance(item, dict):
                yield "financial_metrics", item


def _record_end_date(item: Dict[str, Any]) -> str:
    for key in ["end_date", "report_date", "end", "date"]:
        value = str(item.get(key) or "").strip()
        if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", value):
            return value
    return ""


def _record_has_fiscal_alias(item: Dict[str, Any], summary_period: str) -> bool:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    target = re.fullmatch(r"FY(20\d{2})", str(summary_period or "").upper())
    target_year = int(target.group(1)) if target else None
    for source in [item, metadata]:
        for key in ["fy", "fiscal_year"]:
            try:
                if target_year is not None and int(str(source.get(key) or "").strip()) == target_year:
                    return True
            except ValueError:
                continue
        for key in ["fiscal_period", "fiscalPeriod", "fiscal_year_label"]:
            if str(source.get(key) or "").strip().upper() == summary_period:
                return True
        fp = str(source.get("fp") or source.get("fiscal_quarter") or "").strip().upper()
        if target_year is not None and fp == "FY":
            try:
                if int(str(source.get("fy") or source.get("fiscal_year") or "").strip()) == target_year:
                    return True
            except ValueError:
                continue
    return False


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
    if "eastmoney" in joined or "yahoo" in joined or "reuters" in joined:
        return False
    return any(term in joined for term in ["primary", "sec", "edgar", "cninfo", "sse", "szse", "exchange", "hkex", "company ir", "official"])


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


# Clean overrides for broader mojibake enforcement.
def _check_mojibake_policy(artifacts: Dict[str, Any], issues: List[Dict[str, Any]]) -> None:
    checks = {
        "report_md": artifacts.get("report_md"),
        "report_html": artifacts.get("report_html"),
        "charts": artifacts.get("charts"),
        "citations": artifacts.get("citations"),
        "summary": artifacts.get("summary"),
        "pdf_section_summaries": artifacts.get("pdf_section_summaries"),
        "report_section_contracts": artifacts.get("report_section_contracts"),
    }
    for artifact_name, value in checks.items():
        issue = build_mojibake_quality_issue(artifact_name, value)
        if issue:
            issues.append(issue)


def _check_claim_citation_policy(artifacts: Dict[str, Any], issues: List[Dict[str, Any]]) -> None:
    claims = artifacts.get("claims", []) if isinstance(artifacts.get("claims"), list) else []
    if not claims:
        return
    text = _report_text(artifacts)
    citations = artifacts.get("citations", []) if isinstance(artifacts.get("citations"), list) else []
    citation_ids = {
        str(item.get("evidence_id") or "").strip()
        for item in citations
        if isinstance(item, dict) and str(item.get("evidence_id") or "").strip()
    }
    missing: List[str] = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        for eid in claim.get("evidence_ids") or []:
            evidence_id = str(eid or "").strip()
            if not evidence_id:
                continue
            canonical_id = _canonical_evidence_id(evidence_id)
            if (
                evidence_id in citation_ids
                or evidence_id in text
                or canonical_id in citation_ids
                or (canonical_id != evidence_id and canonical_id in text)
            ):
                continue
            missing.append(evidence_id)
    unique_missing = sorted(set(missing))
    if unique_missing:
        preview = ", ".join(unique_missing[:5])
        _issue(
            issues,
            "blocker",
            "claim_citation_policy",
            f"claim evidence ids are absent from final citations/body: {preview}",
        )


def _canonical_evidence_id(evidence_id: str) -> str:
    value = str(evidence_id or "").strip()
    if not value:
        return ""
    return re.split(r"__(?:paragraph|section|page|table)_\d+_chunk_[0-9a-f]+", value, maxsplit=1, flags=re.I)[0]


def _contains_mojibake(text: str) -> bool:
    return looks_like_mojibake(text)
