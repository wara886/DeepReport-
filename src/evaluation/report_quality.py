"""Objective quality evaluation for generated company research reports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List


GROUP_WEIGHTS = {
    "structure": 0.18,
    "evidence": 0.20,
    "financial": 0.18,
    "multimodal": 0.12,
    "professional_depth": 0.20,
    "compliance": 0.12,
}

EMPTY_MARKERS = ("暂无可验证结论", "暂无结论", "无法判断", "待补充", "N/A")
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
        "compliance": _score_compliance(artifacts, issues),
    }
    _check_delivery_policy(artifacts, issues)
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
        "charts": _as_list(_read_json(paths.outputs_dir / "charts.json", [])),
        "pdf_sections": _as_list(_read_json(paths.outputs_dir / "pdf_sections.json", [])),
        "profile": _read_json(paths.outputs_dir / "company_profile_extracted.json", {}),
        "verification": _read_json(paths.outputs_dir / "verification_report.json", {}),
        "scorecard": _read_json(paths.outputs_dir / "company_report_scorecard.json", {}),
        "search_meta": _read_json(paths.outputs_dir / "search_meta.json", {}),
        "agent_collaboration_trace": _read_json(paths.outputs_dir / "agent_collaboration_trace.json", {}),
        "report_md": _read_text(paths.reports_dir / "report.md"),
        "report_html": _read_text(paths.reports_dir / "report.html"),
        "report_json": _read_json(paths.reports_dir / "report.json", {}),
    }


def _score_structure(artifacts: Dict[str, Any], issues: List[Dict[str, Any]]) -> float:
    text = _report_text(artifacts)
    required = {
        "executive_summary": ("执行摘要", "摘要", "核心观点", "summary"),
        "business_profile": ("主营业务", "业务画像", "公司画像", "business"),
        "financial_analysis": ("财务", "三表", "盈利", "现金流", "financial"),
        "valuation": ("估值", "valuation", "p/e", "p/b"),
        "risk": ("风险", "risk"),
        "investment_conclusion": ("投资建议", "投资结论", "评级", "conclusion"),
    }
    present = {key: _contains_any(text, terms) for key, terms in required.items()}
    for key, ok in present.items():
        if not ok:
            _issue(issues, "blocker", "structure", f"缺少必备章节或段落：{key}")
    if any(marker in text for marker in EMPTY_MARKERS):
        _issue(issues, "blocker", "structure", "报告包含空洞占位结论或暂无可验证结论")
    empty_count = sum(text.count(marker) for marker in EMPTY_MARKERS)
    if empty_count >= 3:
        _issue(issues, "fatal", "structure", f"空洞占位表达过多：{empty_count} 处")
    return round(sum(1 for ok in present.values() if ok) / len(required), 4)


def _score_evidence(artifacts: Dict[str, Any], issues: List[Dict[str, Any]]) -> float:
    claims = artifacts["claims"]
    evidence = artifacts["evidence"]
    citations = artifacts["citations"]
    text = _report_text(artifacts)
    if not claims:
        _issue(issues, "fatal", "evidence", "claims.json 为空，无法形成论点-论据链")
        return 0.0
    covered = 0
    for claim in claims:
        evidence_ids = claim.get("evidence_ids") if isinstance(claim, dict) else []
        if isinstance(evidence_ids, list) and evidence_ids:
            covered += 1
        else:
            _issue(issues, "blocker", "evidence", f"claim 缺少 evidence_ids：{claim.get('claim_id') if isinstance(claim, dict) else '-'}")
    coverage = covered / max(1, len(claims))
    citation_in_body = 1.0 if re.search(r"(ev_|evidence|citation|来源|引用|\[\d+\])", text, flags=re.IGNORECASE) else 0.0
    if citations and citation_in_body == 0.0:
        _issue(issues, "blocker", "evidence", "引用表存在，但正文没有明显引用标记")
    primary = sum(1 for item in evidence if _is_primary_source(item))
    primary_ratio = primary / max(1, len(evidence))
    if primary_ratio < 0.35:
        _issue(issues, "warning", "evidence", f"权威/一手来源占比偏低：{primary_ratio:.2f}")
    return round(0.55 * coverage + 0.25 * min(1.0, len(citations) / max(1, len(claims))) + 0.2 * max(citation_in_body, primary_ratio), 4)


def _score_financial(artifacts: Dict[str, Any], issues: List[Dict[str, Any]]) -> float:
    tables = artifacts["tables"]
    metrics = artifacts["financial_metrics"]
    text = _report_text(artifacts)
    statements = _statement_names_from_tables(tables)
    has_income = any("income" in item or "利润" in item for item in statements)
    has_balance = any("balance" in item or "资产" in item for item in statements)
    has_cashflow = any("cash" in item or "现金" in item for item in statements) or _has_cashflow_gap_explained(text)
    for ok, name in [(has_income, "利润表"), (has_balance, "资产负债表"), (has_cashflow, "现金流量表")]:
        if not ok:
            _issue(issues, "blocker", "financial", f"缺少{name}摘要")
    if SCI_NOTATION_RE.search(text):
        _issue(issues, "blocker", "financial", "正文包含科学计数法，财务数值展示不专业")
    if not re.search(r"(亿元|万美元|亿美元|%|pct|bps|million|billion)", text, flags=re.IGNORECASE):
        _issue(issues, "warning", "financial", "正文缺少清晰单位或百分比表达")
    metric_score = 1.0 if metrics else 0.45
    period_alignment = _period_alignment_score(artifacts, issues)
    table_score = (int(has_income) + int(has_balance) + int(has_cashflow)) / 3
    return round(0.45 * table_score + 0.25 * metric_score + 0.2 * period_alignment + 0.1 * (0 if SCI_NOTATION_RE.search(text) else 1), 4)


def _score_multimodal(artifacts: Dict[str, Any], issues: List[Dict[str, Any]]) -> float:
    charts = artifacts["charts"]
    tables = artifacts["tables"]
    text = _report_text(artifacts)
    if not charts:
        _issue(issues, "blocker", "multimodal", "缺少图表产物")
    useful = 0
    for chart in charts:
        title = str(chart.get("title") or chart.get("chart_id") or "") if isinstance(chart, dict) else ""
        if _contains_any(title, ("收入", "利润", "现金", "指标", "margin", "revenue", "income", "metrics")):
            useful += 1
    if charts and useful == 0:
        _issue(issues, "warning", "multimodal", "图表未明显服务于财务分析")
    figure_mentioned = 1.0 if _contains_any(text, ("图", "表", "chart", "figure")) else 0.0
    return round(0.45 * min(1.0, len(charts) / 2) + 0.25 * min(1.0, useful / 1) + 0.2 * min(1.0, len(tables) / 3) + 0.1 * figure_mentioned, 4)


def _score_professional_depth(artifacts: Dict[str, Any], issues: List[Dict[str, Any]]) -> float:
    text = _report_text(artifacts)
    profile = artifacts["profile"]
    checks = {
        "business_profile": bool(profile) or _contains_any(text, ("主营业务", "业务画像", "产品", "渠道", "business")),
        "peer_compare": _contains_any(text, ("同行", "可比公司", "竞品", "peer")),
        "valuation": _contains_any(text, ("估值", "P/E", "P/B", "市盈率", "市净率", "valuation")),
        "sensitivity": _contains_any(text, ("敏感性", "情景", "scenario", "sensitivity")),
        "risk": _contains_any(text, ("风险", "risk")),
        "investment": _contains_any(text, ("投资建议", "投资结论", "评级", "中性", "买入", "持有")),
    }
    for key, ok in checks.items():
        if not ok:
            severity = "blocker" if key in {"business_profile", "risk", "investment"} else "warning"
            _issue(issues, severity, "professional_depth", f"专业深度不足：缺少 {key}")
    if _section_is_framework_only(text, ("同行对比", "同行比较")):
        _issue(issues, "blocker", "professional_depth", "同行对比只有框架或待补说明，缺少可读结论")
    if _section_is_framework_only(text, ("估值敏感性", "敏感性分析")):
        _issue(issues, "blocker", "professional_depth", "敏感性分析只有框架或待补说明，缺少变量方向和影响")
    if _valuation_is_unusable_without_reason(text):
        _issue(issues, "blocker", "professional_depth", "估值缺失但没有明确估值不可用原因")
    if not _investment_conclusion_has_direction_and_reason(text):
        _issue(issues, "blocker", "professional_depth", "投资结论缺少明确方向和理由")
    return round(sum(1 for ok in checks.values() if ok) / len(checks), 4)


def _score_compliance(artifacts: Dict[str, Any], issues: List[Dict[str, Any]]) -> float:
    text = _report_text(artifacts)
    checks = {
        "risk_disclosure": _contains_any(text, ("风险提示", "风险因素", "risk")),
        "source_disclosure": _contains_any(text, ("资料来源", "数据来源", "来源", "citation")),
        "rating_explanation": _contains_any(text, ("评级", "投资建议", "中性", "买入", "持有")),
        "use_limitation": _contains_any(text, ("不构成投资建议", "仅供参考", "使用限制", "免责声明")),
        "conflict_statement": _contains_any(text, ("利益冲突", "独立性", "披露")),
    }
    for key, ok in checks.items():
        if not ok:
            _issue(issues, "warning", "compliance", f"合规披露不足：缺少 {key}")
    return round(sum(1 for ok in checks.values() if ok) / len(checks), 4)


def _check_delivery_policy(artifacts: Dict[str, Any], issues: List[Dict[str, Any]]) -> None:
    summary = artifacts.get("summary", {}) if isinstance(artifacts.get("summary"), dict) else {}
    entity = summary.get("entity_resolution", {}) if isinstance(summary.get("entity_resolution"), dict) else {}
    resolved_symbol = str(entity.get("resolved_symbol") or summary.get("symbol") or "").strip()
    confidence = float(entity.get("confidence") or entity.get("resolution_confidence") or 0.0)
    if not resolved_symbol:
        _issue(issues, "blocker", "delivery_policy", "无法确认上市公司标的，不能生成正式公司/个股研报")
    elif confidence and confidence < 0.45:
        _issue(issues, "blocker", "delivery_policy", f"上市公司身份解析置信度过低：{confidence:.2f}")

    report_text = _report_text(artifacts)
    memory_trace = artifacts.get("agent_collaboration_trace", {})
    memory_text = json.dumps(memory_trace, ensure_ascii=False) if isinstance(memory_trace, dict) else ""
    if "DurableMemory" in report_text or "[DurableMemory]" in report_text:
        _issue(issues, "blocker", "delivery_policy", "正文疑似把 memory 内容当作事实来源")
    if memory_text and "facts require evidence/citation/verifier" not in memory_text:
        _issue(issues, "warning", "delivery_policy", "多智能体 trace 未清楚声明 memory 不可替代事实证据")

    engines = _search_engines_used(artifacts.get("search_meta", {}), summary)
    if len(set(engines)) < 2:
        _issue(issues, "warning", "delivery_policy", "免费公开数据源尝试不足，至少应记录两个以上数据源/搜索引擎")
    if engines and _only_local_sources(engines) and not _contains_any(report_text, ("数据缺口", "已尝试", "公开来源", "source gap", "unavailable")):
        _issue(issues, "blocker", "delivery_policy", "仅使用本地来源但正文未说明实时/公开来源缺口")

    if _contains_any(report_text, ("持续关注", "谨慎观察", "中性")) and not _contains_any(
        report_text, ("因为", "理由", "增长驱动", "竞争压力", "估值约束", "risk")
    ):
        _issue(issues, "blocker", "delivery_policy", "投资结论方向存在但缺少理由、增长驱动、竞争压力或估值约束")


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
        any("income" in item or "利润" in item for item in statements)
        and any("balance" in item or "资产" in item for item in statements)
        and (any("cash" in item or "现金" in item for item in statements) or _has_cashflow_gap_explained(text))
        and _body_has_three_statement_summary(text)
    )
    checks = {
        "non_empty_executive_summary": _contains_any(text, ("执行摘要", "摘要", "核心观点", "summary")) and not _section_is_empty(text, ("执行摘要", "摘要", "核心观点")),
        "non_empty_risk": _contains_any(text, ("风险", "risk")) and not _section_is_empty(text, ("风险",)),
        "non_empty_investment_conclusion": _contains_any(text, ("投资建议", "投资结论", "评级")) and not _section_is_empty(text, ("投资建议", "投资结论", "评级")),
        "has_three_table_summary": has_three_tables,
        "has_business_profile": bool(artifacts["profile"]) or _contains_any(text, ("主营业务", "业务画像", "公司画像", "business")),
        "valuation_or_reason": _contains_any(text, ("估值", "P/E", "P/B", "市盈率", "市净率", "估值不可用原因", "估值暂不可用")),
    }
    for key, ok in checks.items():
        if not ok:
            _issue(issues, "fatal" if key in {"non_empty_executive_summary", "non_empty_risk", "non_empty_investment_conclusion"} else "blocker", "gate", f"质量门禁未通过：{key}")
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
    return _contains_any(text, ("现金流量表缺口", "现金流量表数据不足", "经营现金流或自由现金流字段", "现金转化率判断"))


def _body_has_three_statement_summary(text: str) -> bool:
    return (
        _contains_any(text, ("利润表", "收入", "营收", "净利润", "income statement"))
        and _contains_any(text, ("资产负债表", "总资产", "股东权益", "净资产", "balance sheet"))
        and (_contains_any(text, ("现金流量表", "经营现金流", "自由现金流", "现金流", "cash flow")) or _has_cashflow_gap_explained(text))
    )


def _section_is_framework_only(text: str, titles: Iterable[str]) -> bool:
    body = _section_body(text, titles)
    if not body:
        return False
    framework_markers = ("框架", "待补", "缺少可量化", "缺少同业", "尚未完整", "暂无")
    conclusion_markers = ("因此", "说明", "压力", "驱动", "约束", "优于", "弱于", "中性", "积极", "谨慎")
    return _contains_any(body, framework_markers) and not _contains_any(body, conclusion_markers)


def _valuation_is_unusable_without_reason(text: str) -> bool:
    if not _contains_any(text, ("估值", "P/E", "P/B", "P/S", "市盈率", "市净率")):
        return True
    has_multiple = bool(re.search(r"(P/E|P/B|P/S|市盈率|市净率)\s*(约为|为|:|：)?\s*\d", text, flags=re.I))
    has_reason = _contains_any(text, ("估值不可用原因", "估值暂不可用", "缺少市值", "缺少股本", "缺少净利润", "缺少净资产"))
    return not has_multiple and not has_reason


def _investment_conclusion_has_direction_and_reason(text: str) -> bool:
    body = _section_body(text, ("投资结论", "投资建议", "评级"))
    if not body:
        return False
    has_direction = _contains_any(body, ("中性", "审慎", "谨慎", "积极", "买入", "持有", "卖出", "观察"))
    has_reason = _contains_any(body, ("基于", "因为", "由于", "来自", "驱动", "压力", "风险", "估值", "现金流", "证据"))
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
        _issue(issues, "warning", "financial", f"claim period 与 summary period 可能不一致：{mismatches[:5]}")
        return 0.55
    return 1.0


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
        ("执行摘要", "摘要", "核心观点", "summary"),
        ("主营业务", "业务画像", "公司画像", "产品", "渠道", "business"),
        ("财务", "三表", "盈利", "现金", "financial"),
        ("估值", "市盈率", "市净率", "valuation", "p/e", "p/b"),
        ("风险", "风险提示", "风险因素", "risk"),
        ("投资建议", "投资结论", "评级", "中性", "买入", "持有", "conclusion"),
        ("同行", "可比公司", "竞品", "peer"),
        ("敏感性", "情景", "scenario", "sensitivity"),
        ("资料来源", "数据来源", "来源", "citation"),
        ("不构成投资建议", "仅供参考", "使用限制", "免责声明"),
        ("利益冲突", "独立性", "披露"),
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
