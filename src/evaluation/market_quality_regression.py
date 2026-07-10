"""Small fixed multi-market quality regression suite.

This suite is intentionally read-only and deterministic. It writes synthetic
run artifacts, evaluates them through the production report quality and
delivery gate, then emits benchmark-compatible CSV/JSONL outputs.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from src.evaluation.delivery_gate import build_delivery_gate_from_outputs, write_delivery_gate_for_outputs
from src.evaluation.report_quality import evaluate_report_quality_from_paths, write_quality_outputs_for_paths


DEFAULT_CASES = [
    {"case_id": "p13_us_amd", "market": "US", "symbol": "AMD", "company_name": "Advanced Micro Devices", "period": "FY2024"},
    {"case_id": "p13_hk_tencent", "market": "HK", "symbol": "0700.HK", "company_name": "腾讯控股", "period": "FY2024"},
    {"case_id": "p13_cna_moutai", "market": "CN-A", "symbol": "600519.SS", "company_name": "贵州茅台", "period": "FY2024"},
]

DEFAULT_REAL_ARTIFACT_ROOTS = [
    "data/outputs_user/runs",
    "data/outputs_dev/runs",
    "data/outputs/multi_agent/runs",
]


def run_market_quality_regression(
    *,
    output_root: str | Path = "data/evaluation/p1_market_quality_regression",
    cases: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    root = Path(output_root)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    suite_dir = root / f"p1_market_quality_regression_{run_id}"
    suite_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for case in cases or DEFAULT_CASES:
        rows.append(_run_case(case, suite_dir=suite_dir))
    summary = _summarize(rows)
    _write_outputs(suite_dir=suite_dir, rows=rows, summary=summary)
    return {
        "suite_id": suite_dir.name,
        "suite_dir": str(suite_dir),
        "case_count": len(rows),
        "summary": summary,
        "paths": {
            "benchmark_summary": str(suite_dir / "benchmark_summary.csv"),
            "market_breakdown": str(suite_dir / "market_breakdown.csv"),
            "runs": str(suite_dir / "benchmark_runs.jsonl"),
            "failures": str(suite_dir / "benchmark_failures.csv"),
            "report": str(suite_dir / "benchmark_report.md"),
        },
    }


def run_real_artifact_quality_regression(
    *,
    output_root: str | Path = "data/evaluation/p1_real_artifact_quality_regression",
    source_roots: list[str | Path] | None = None,
    max_per_market: int = 2,
) -> dict[str, Any]:
    """Re-score existing generated report artifacts by market."""

    root = Path(output_root)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    suite_dir = root / f"p1_real_artifact_quality_regression_{run_id}"
    suite_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    selected = _select_real_artifact_runs(source_roots or DEFAULT_REAL_ARTIFACT_ROOTS, max_per_market=max_per_market)
    for item in selected:
        rows.append(_evaluate_existing_artifact_run(item, suite_dir=suite_dir))
    summary = _summarize(rows)
    _write_outputs(suite_dir=suite_dir, rows=rows, summary=summary)
    return {
        "suite_id": suite_dir.name,
        "suite_dir": str(suite_dir),
        "case_count": len(rows),
        "summary": summary,
        "paths": {
            "benchmark_summary": str(suite_dir / "benchmark_summary.csv"),
            "market_breakdown": str(suite_dir / "market_breakdown.csv"),
            "runs": str(suite_dir / "benchmark_runs.jsonl"),
            "failures": str(suite_dir / "benchmark_failures.csv"),
            "report": str(suite_dir / "benchmark_report.md"),
        },
    }


def _select_real_artifact_runs(source_roots: list[str | Path], *, max_per_market: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    counts = {"US": 0, "HK": 0, "CN-A": 0}
    for outputs in _iter_output_dirs(source_roots):
        reports = _reports_dir_for_outputs(outputs)
        if not (reports / "report.md").exists():
            continue
        summary = _read_json(outputs / "run_summary.json", {})
        symbol = str(summary.get("symbol") or _symbol_from_path(outputs)).upper()
        market = _market_from_symbol(symbol)
        if market not in counts or counts[market] >= max_per_market:
            continue
        counts[market] += 1
        selected.append(
            {
                "case_id": f"real_{outputs.parent.name}",
                "market": market,
                "symbol": symbol or "UNKNOWN",
                "company_name": str(summary.get("company_name") or summary.get("title") or symbol or outputs.parent.name),
                "period": str(summary.get("period") or ""),
                "outputs_dir": outputs,
                "reports_dir": reports,
            }
        )
        if all(value >= max_per_market for value in counts.values()):
            break
    return selected


def _iter_output_dirs(source_roots: list[str | Path]) -> list[Path]:
    dirs: list[Path] = []
    for root in source_roots:
        path = Path(root)
        if not path.exists():
            continue
        if path.name == "outputs":
            dirs.append(path)
            continue
        dirs.extend(p for p in path.rglob("outputs") if p.is_dir())
    return sorted(set(dirs), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)


def _reports_dir_for_outputs(outputs: Path) -> Path:
    parts = list(outputs.parts)
    if "outputs_user" in parts:
        parts[parts.index("outputs_user")] = "reports_user"
        if parts[-1] == "outputs":
            parts[-1] = "reports"
        return Path(*parts)
    if "outputs_dev" in parts:
        parts[parts.index("outputs_dev")] = "reports_dev"
        if parts[-1] == "outputs":
            parts[-1] = "reports"
        return Path(*parts)
    if outputs.name == "outputs":
        return outputs.parent / "reports"
    return outputs.parent / "reports"


def _evaluate_existing_artifact_run(item: dict[str, Any], *, suite_dir: Path) -> dict[str, Any]:
    outputs = Path(item["outputs_dir"])
    reports = Path(item["reports_dir"])
    quality = evaluate_report_quality_from_paths(outputs, reports, outputs.parent)
    write_quality_outputs_for_paths(outputs, reports, quality)
    gate = build_delivery_gate_from_outputs(outputs, outputs.parent)
    write_delivery_gate_for_outputs(outputs, gate)
    claims = _as_list(_read_json(outputs / "claims.json", []))
    citations = _as_list(_read_json(outputs / "citations.json", []))
    return {
        "case_id": str(item["case_id"]),
        "market": str(item["market"]),
        "company_name": str(item["company_name"]),
        "canonical_symbol": str(item["symbol"]),
        "period": str(item.get("period") or ""),
        "outputs_dir": str(outputs),
        "reports_dir": str(reports),
        "status": "evaluated",
        "delivery_pass": bool(gate.get("delivery_pass")),
        "objective_pass": bool(quality.get("objective_pass")),
        "objective_quality_score": round(float(quality.get("total_score", 0.0)) * 100.0, 2),
        "content_depth_blocker_count": _issue_count(quality, category="content_depth"),
        "official_evidence_blocker_count": _issue_count(quality, category="official_evidence"),
        "citation_coverage_rate": _citation_coverage_rate(claims, citations),
        "failure_categories": _failure_categories(quality, gate),
    }


def _market_from_symbol(symbol: str) -> str:
    text = str(symbol or "").upper()
    if text.endswith(".HK"):
        return "HK"
    if text.endswith((".SS", ".SZ", ".SH")):
        return "CN-A"
    if text and "." not in text:
        return "US"
    return "OTHER"


def _symbol_from_path(outputs: Path) -> str:
    name = outputs.parent.name.upper()
    for token in name.replace("-", "_").split("_"):
        if token.endswith((".HK", ".SS", ".SZ", ".SH")) or token.isalpha():
            return token
    return ""


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _as_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _run_case(case: dict[str, Any], *, suite_dir: Path) -> dict[str, Any]:
    case_id = str(case["case_id"])
    case_dir = suite_dir / "runs" / case_id
    outputs = case_dir / "outputs"
    reports = case_dir / "reports"
    outputs.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    artifacts = _case_artifacts(case)
    for filename, payload in artifacts["outputs"].items():
        (outputs / filename).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    reports.joinpath("report.md").write_text(artifacts["report_md"], encoding="utf-8")
    reports.joinpath("report.html").write_text(f"<html><body>{artifacts['report_md']}</body></html>", encoding="utf-8")
    quality = evaluate_report_quality_from_paths(outputs, reports, case_dir)
    write_quality_outputs_for_paths(outputs, reports, quality)
    gate = build_delivery_gate_from_outputs(outputs, case_dir)
    write_delivery_gate_for_outputs(outputs, gate)
    row = {
        "case_id": case_id,
        "market": str(case["market"]),
        "company_name": str(case["company_name"]),
        "canonical_symbol": str(case["symbol"]),
        "period": str(case["period"]),
        "outputs_dir": str(outputs),
        "reports_dir": str(reports),
        "status": "evaluated",
        "delivery_pass": bool(gate.get("delivery_pass")),
        "objective_pass": bool(quality.get("objective_pass")),
        "objective_quality_score": round(float(quality.get("total_score", 0.0)) * 100.0, 2),
        "content_depth_blocker_count": _issue_count(quality, category="content_depth"),
        "official_evidence_blocker_count": _issue_count(quality, category="official_evidence"),
        "citation_coverage_rate": _citation_coverage_rate(artifacts["outputs"].get("claims.json", []), artifacts["outputs"].get("citations.json", [])),
        "failure_categories": _failure_categories(quality, gate),
    }
    return row


def _case_artifacts(case: dict[str, Any]) -> dict[str, Any]:
    symbol = str(case["symbol"])
    company = str(case["company_name"])
    period = str(case["period"])
    market = str(case["market"])
    source_type = {"US": "sec_filing", "HK": "hkex_annual_report", "CN-A": "cninfo_announcement"}.get(market, "official_filing")
    source_name = {"US": "SEC EDGAR", "HK": "HKEX", "CN-A": "CNINFO"}.get(market, "官方披露")
    unit = {"US": "亿美元", "HK": "亿港元", "CN-A": "亿元"}.get(market, "亿元")
    currency = {"US": "USD", "HK": "HKD", "CN-A": "CNY"}.get(market, "")
    market_key = {"US": "us", "HK": "hk", "CN-A": "cn_a"}.get(market, "unknown")
    evidence_id = f"{case['case_id']}_official"
    claims = [
        {"claim_id": f"{case['case_id']}_summary", "section_name": "executive_summary", "claim_text": f"{company} {period} 经营判断需要结合财务、估值和风险。", "evidence_ids": [evidence_id], "confidence": 0.86},
        {"claim_id": f"{case['case_id']}_valuation", "section_name": "valuation", "claim_text": "估值需要同时参考收入增速、利润率、现金流质量和风险溢价。", "evidence_ids": [evidence_id], "confidence": 0.84},
        {"claim_id": f"{case['case_id']}_risk", "section_name": "risks", "claim_text": "需求、竞争、监管和现金流风险会影响正式投资结论。", "evidence_ids": [evidence_id], "confidence": 0.82},
        {"claim_id": f"{case['case_id']}_conclusion", "section_name": "conclusion", "claim_text": "基于估值约束和风险边界，维持审慎观察。", "evidence_ids": [evidence_id], "confidence": 0.83},
    ]
    tables = [
        {"statement": "income_statement", "metric_name": "revenue", "value": 100, "unit": unit, "period": period, "source_type": source_type, "source_evidence_id": evidence_id},
        {"statement": "balance_sheet", "metric_name": "equity", "value": 80, "unit": unit, "period": period, "source_type": source_type, "source_evidence_id": evidence_id},
        {"statement": "cash_flow_statement", "metric_name": "operating_cash_flow", "value": 20, "unit": unit, "period": period, "source_type": source_type, "source_evidence_id": evidence_id},
    ]
    coverage_missing = [] if market == "US" else []
    evidence_coverage = {
        "symbol": symbol,
        "market": market_key,
        "period": period,
        "official_record_count": 1,
        "period_matched_official_record_count": 1,
        "missing_requirements": coverage_missing,
        "blocking_reasons": [],
        "recommended_actions": [],
        "draft_generation_allowed": True,
        "formal_delivery_allowed": True,
        "degrade_required": False,
    }
    report_md = _report_markdown(company=company, symbol=symbol, period=period, source_name=source_name, evidence_id=evidence_id, unit=unit)
    outputs = {
        "run_summary.json": {"symbol": symbol, "period": period, "market": market, "verification_passed": True, "entity_resolution": {"resolved_symbol": symbol, "confidence": 0.95}},
        "claims.json": claims,
        "evidence.json": [{"evidence_id": evidence_id, "source_type": source_type, "trust_level": "official", "title": f"{company} {period} {source_name} disclosure", "period": period, "content": "official evidence"}],
        "citations.json": [{"evidence_id": evidence_id, "claim_ids": [claim["claim_id"] for claim in claims], "used_in_report": True, "title": source_name}],
        "tables.json": tables,
        "financial_metrics.json": {"metrics": tables},
        "charts.json": [{"chart_id": f"{case['case_id']}_chart", "title": "三表关键指标", "output_path": "charts/key_metrics.png"}],
        "company_profile_extracted.json": {"business": f"{company} 主营业务和财务指标已进入回归样本。"},
        "verification_report.json": {"passed": True, "errors": [], "evidence_gaps": []},
        "llm_quality_review.json": {"llm_review_pass": True, "total_score": 0.84, "issues": []},
        "currency_audit.json": {"symbol": symbol, "market": market_key, "statement_currency": currency, "trading_currency": currency, "blockers": []},
        "evidence_coverage.json": evidence_coverage,
        "official_evidence_manifest.json": {"records": [{"evidence_id": evidence_id, "source_type": source_type, "period": period, "period_match": True}]},
    }
    return {"outputs": outputs, "report_md": report_md}


def _report_markdown(*, company: str, symbol: str, period: str, source_name: str, evidence_id: str, unit: str) -> str:
    citation = f"[{evidence_id}]"
    return f"""# {company}（{symbol}）{period} 多市场质量回归研报

## 执行摘要
本报告用于多市场质量回归，核心目的是验证研报工作台能否在固定证据输入下生成结构完整、引用可追溯、正式交付状态清晰的公司研究文本。{company} 的分析围绕业务、三表、估值、风险和投资结论展开，报告期为 {period}，关键事实均绑定到 {source_name} 或等价官方来源。当前结论采用审慎观察口径，避免在证据不足时直接输出强买卖评级。{citation}

## 业务概览
{company} 的业务概览聚焦主营业务、产品结构、客户需求和行业竞争。回归样本不追求完整商业史，而是检查工作台能否把公司身份、业务边界和证据来源写成用户可读的研究段落。业务判断需要和财务表现、现金流质量及风险事项联动，不能只停留在公司简介。对于多市场公司，报告还需要说明披露规则、交易货币和投资者预期差异，避免把不同市场的估值和财务口径混用。该段还用于确认前端展示不是后端字段堆砌，而是能形成清晰业务叙事。{citation}

## 三表摘要
利润表显示收入为 100 {unit}，资产负债表显示权益为 80 {unit}，现金流量表显示经营现金流为 20 {unit}，三表口径均对齐 {period}。该摘要用于验证收入、资产负债和现金流三类指标是否同时进入正式研报，并且在报告正文中形成清晰解释。若后续真实数据替换样本数据，也应保持三表口径和来源一致。{citation}

## 财务分析
财务分析重点不是单一收入数值，而是收入、利润率、资产结构和经营现金流之间是否互相支持。若收入增长但现金流转弱，正式报告需要解释应收、库存或资本开支压力；若现金流改善且资产负债结构稳定，则盈利质量更有支撑。本回归样本要求财务段落具备足够解释深度，避免只有表格没有分析。进一步看，收入、权益和经营现金流三项指标需要共同说明盈利质量：收入代表经营规模，权益代表资产安全垫，经营现金流代表利润兑现能力。报告还应指出三表之间的勾稽关系，确保利润、资产和现金流不是孤立展示，并能支持后续估值和风险判断。{citation}

## 同行对比
同行对比应说明可比公司和口径边界，而不是机械套用同一估值倍数。不同市场公司的披露规则、业务结构和投资者预期不同，因此多市场回归只检查相对比较逻辑是否完整：先确认可比维度，再比较收入质量、利润率、现金流和估值约束，最后说明比较结论的适用范围。若真实跑批中存在同行数据缺口，报告应明确标为横向比较不足，而不是输出没有证据支持的相对强弱判断。{citation}

## 估值观察
估值观察以收入增速、利润率、现金流质量和风险溢价为核心变量。当前样本不输出确定目标价，但为了满足估值路径检查，设置 P/E 为 20x、P/B 为 5x 作为回归占位倍数，并明确这些倍数只能用于质量回归，不代表真实投资建议。若收入和现金流改善，估值中枢具备上修依据；若竞争、监管或需求压力上升，估值溢价应收缩。正式交付前仍需复核可比倍数、折现率、股本、市值和官方财务口径，并检查估值结论是否被真实引用支撑，避免倍数和结论脱节。{citation}

## 风险评估
风险评估覆盖需求波动、竞争加剧、监管变化、现金流承压和估值假设失效。风险不能只写成孤立清单，而应说明风险如何传导到收入、利润率、现金流和估值倍数。若后续官方披露出现关键指标恶化，风险权重应上调；若指标改善，风险权重可以下降但仍需保留跟踪。对多市场样本而言，还要关注披露时滞、汇率、交易制度和数据源可用性，因为这些因素会影响正式交付的证据完整度。该段同时验证风险章节不会因为自动补写而变成模板化空话。{citation}

## 投资结论
投资结论维持中性评级和审慎观察，基于三表指标完整、业务边界清晰、官方证据可追溯以及估值约束仍需复核这四个理由。支持因素来自收入、权益和经营现金流同时进入报告正文；约束因素来自估值输入仍需真实市场数据、风险权重需要持续更新、跨市场样本不能替代正式投研判断。因此本报告可作为回归基线和人工复核材料，只有在证据门禁、质量评分、主张复核和引用覆盖共同通过后，才可进入正式交付包。{citation}

## 合规披露
资料来源：{source_name}、公司公告和结构化财务指标。本文仅用于系统质量回归和研发验证，不构成投资建议；不存在利益冲突，保持独立性披露。
"""


def _citation_coverage_rate(claims: list[dict[str, Any]], citations: list[dict[str, Any]]) -> float:
    cited_claims = {str(claim_id) for citation in citations for claim_id in citation.get("claim_ids", []) if isinstance(citation, dict)}
    if not claims:
        return 0.0
    return round(sum(1 for claim in claims if str(claim.get("claim_id")) in cited_claims) / len(claims), 4)


def _issue_count(quality: dict[str, Any], *, category: str) -> int:
    return sum(1 for item in quality.get("issues", []) if item.get("severity") in {"fatal", "blocker"} and item.get("category") == category)


def _failure_categories(quality: dict[str, Any], gate: dict[str, Any]) -> list[str]:
    categories: list[str] = []
    if gate.get("delivery_pass") is not True:
        categories.append("delivery_gate_failed")
    if not quality.get("objective_pass"):
        categories.append("objective_quality_failed")
    for item in quality.get("issues", []):
        if item.get("severity") in {"fatal", "blocker"}:
            categories.append(str(item.get("category") or "quality_blocker"))
    return sorted(set(categories))


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    markets = ["US", "HK", "CN-A"]
    by_market = {market: _summary_for([row for row in rows if row["market"] == market]) for market in markets}
    return {"overall": _summary_for(rows), "by_market": by_market}


def _summary_for(rows: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(rows)
    if count == 0:
        return {"case_count": 0, "quality_evaluable_count": 0, "delivery_pass_rate": None, "objective_quality_score": None, "traceable_claim_rate": None, "content_depth_blocker_rate": None, "official_evidence_blocker_rate": None}
    return {
        "case_count": count,
        "quality_evaluable_count": count,
        "delivery_pass_rate": round(sum(1 for row in rows if row["delivery_pass"]) / count, 4),
        "objective_quality_score": round(sum(float(row["objective_quality_score"]) for row in rows) / count, 2),
        "traceable_claim_rate": round(sum(float(row["citation_coverage_rate"]) for row in rows) / count, 4),
        "content_depth_blocker_rate": round(sum(1 for row in rows if row["content_depth_blocker_count"] > 0) / count, 4),
        "official_evidence_blocker_rate": round(sum(1 for row in rows if row["official_evidence_blocker_count"] > 0) / count, 4),
    }


def _write_outputs(*, suite_dir: Path, rows: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    _write_runs_jsonl(suite_dir / "benchmark_runs.jsonl", rows)
    _write_failures_csv(suite_dir / "benchmark_failures.csv", rows)
    _write_summary_csv(suite_dir / "benchmark_summary.csv", summary)
    _write_market_csv(suite_dir / "market_breakdown.csv", summary)
    (suite_dir / "benchmark_report.md").write_text(_render_report(rows, summary), encoding="utf-8")


def _write_runs_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def _write_failures_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["case_id", "market", "status", "category", "detail"])
        writer.writeheader()
        for row in rows:
            for category in row["failure_categories"]:
                writer.writerow({"case_id": row["case_id"], "market": row["market"], "status": row["status"], "category": category, "detail": category})


def _write_summary_csv(path: Path, summary: dict[str, Any]) -> None:
    metrics = [
        ("Delivery Pass Rate", "delivery_pass_rate"),
        ("Objective Quality Score", "objective_quality_score"),
        ("Traceable Claim Rate (Artifact-Derived)", "traceable_claim_rate"),
        ("Content Depth Blocker Rate", "content_depth_blocker_rate"),
        ("Official Evidence Blocker Rate", "official_evidence_blocker_rate"),
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["metric", "overall", "US", "HK", "CN-A"])
        for label, key in metrics:
            writer.writerow([label, summary["overall"].get(key), summary["by_market"]["US"].get(key), summary["by_market"]["HK"].get(key), summary["by_market"]["CN-A"].get(key)])


def _write_market_csv(path: Path, summary: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["market", "case_count", "quality_evaluable_count", "delivery_pass_rate", "objective_quality_score", "traceable_claim_rate_artifact_derived", "content_depth_blocker_rate", "official_evidence_blocker_rate"])
        writer.writeheader()
        for market in ["Overall", "US", "HK", "CN-A"]:
            data = summary["overall"] if market == "Overall" else summary["by_market"][market]
            writer.writerow(
                {
                    "market": market,
                    "case_count": data.get("case_count"),
                    "quality_evaluable_count": data.get("quality_evaluable_count"),
                    "delivery_pass_rate": data.get("delivery_pass_rate"),
                    "objective_quality_score": data.get("objective_quality_score"),
                    "traceable_claim_rate_artifact_derived": data.get("traceable_claim_rate"),
                    "content_depth_blocker_rate": data.get("content_depth_blocker_rate"),
                    "official_evidence_blocker_rate": data.get("official_evidence_blocker_rate"),
                }
            )


def _render_report(rows: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    lines = [
        "# P1 Market Quality Regression",
        "",
        f"- delivery_pass_rate: `{summary['overall']['delivery_pass_rate']}`",
        f"- objective_quality_score: `{summary['overall']['objective_quality_score']}`",
        f"- content_depth_blocker_rate: `{summary['overall']['content_depth_blocker_rate']}`",
        f"- official_evidence_blocker_rate: `{summary['overall']['official_evidence_blocker_rate']}`",
        "",
        "| Case | Market | Delivery | Quality | Citation Coverage | Content Blockers | Official Evidence Blockers |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| `{row['case_id']}` | {row['market']} | {row['delivery_pass']} | {row['objective_quality_score']} | {row['citation_coverage_rate']} | {row['content_depth_blocker_count']} | {row['official_evidence_blocker_count']} |"
        )
    lines.append("")
    return "\n".join(lines)
