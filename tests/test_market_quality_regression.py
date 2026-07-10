import json

from src.evaluation.benchmark_summary_importer import load_benchmark_summaries
from src.evaluation.market_quality_regression import run_market_quality_regression, run_real_artifact_quality_regression
from src.evaluation.real_artifact_remediation import repair_real_report_artifact


def test_market_quality_regression_writes_benchmark_compatible_outputs(tmp_path):
    result = run_market_quality_regression(output_root=tmp_path / "p1_regression")
    suite_dir = tmp_path / "p1_regression" / result["suite_id"]

    assert result["case_count"] == 3
    assert result["summary"]["overall"]["delivery_pass_rate"] == 1.0
    assert (suite_dir / "benchmark_summary.csv").exists()
    assert (suite_dir / "market_breakdown.csv").exists()
    assert (suite_dir / "benchmark_runs.jsonl").exists()
    assert (suite_dir / "benchmark_failures.csv").exists()
    assert (suite_dir / "benchmark_report.md").exists()

    rows = [
        json.loads(line)
        for line in (suite_dir / "benchmark_runs.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    markets = {row["market"] for row in rows}
    assert markets == {"US", "HK", "CN-A"}
    assert all(row["status"] == "evaluated" for row in rows)
    assert all(row["delivery_pass"] is True for row in rows)
    assert all(row["content_depth_blocker_count"] == 0 for row in rows)
    assert all(row["official_evidence_blocker_count"] == 0 for row in rows)
    assert all(row["citation_coverage_rate"] == 1.0 for row in rows)


def test_market_quality_regression_outputs_are_imported_by_evaluation_center(tmp_path):
    result = run_market_quality_regression(output_root=tmp_path / "p1_regression")
    suites = load_benchmark_summaries([tmp_path / "p1_regression"])

    assert len(suites) == 1
    suite = suites[0]
    assert suite["artifact_dir"] == result["suite_dir"]
    assert suite["suite_type"] == "regression"
    assert suite["case_count"] == 3
    assert suite["evaluated_count"] == 3
    assert suite["metrics"]["delivery_pass_rate"] == result["summary"]["overall"]["delivery_pass_rate"]
    markets = {row["market"]: row for row in suite["market_breakdown"]}
    assert {"US", "HK", "CN-A"}.issubset(markets)


def test_real_artifact_quality_regression_rescores_existing_outputs(tmp_path):
    source_root = tmp_path / "outputs_user" / "runs"
    _write_real_artifact(source_root / "amd-real" / "outputs", symbol="AMD", period="FY2024")
    _write_real_artifact(source_root / "tencent-real" / "outputs", symbol="0700.HK", period="FY2024")

    result = run_real_artifact_quality_regression(
        output_root=tmp_path / "real_regression",
        source_roots=[source_root],
        max_per_market=1,
    )

    assert result["case_count"] == 2
    rows_path = tmp_path / "real_regression" / result["suite_id"] / "benchmark_runs.jsonl"
    rows = [json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert {row["market"] for row in rows} == {"US", "HK"}
    assert all(row["status"] == "evaluated" for row in rows)
    assert all(row["objective_quality_score"] > 0 for row in rows)
    assert all((tmp_path / "outputs_user" / "runs" / row["case_id"].removeprefix("real_") / "outputs" / "quality_report.json").exists() for row in rows)


def test_real_artifact_remediation_rewrites_thin_core_sections(tmp_path):
    outputs = tmp_path / "outputs_user" / "runs" / "thin-amd" / "outputs"
    reports = tmp_path_reports_for_outputs(outputs)
    _write_real_artifact(outputs, symbol="AMD", period="FY2024")
    reports.joinpath("report.md").write_text(
        """# AMD FY2024

## 执行摘要
摘要太短。

## 业务概览
业务概览正常覆盖产品、客户、行业竞争和披露边界，说明公司业务画像和投资者需要理解的核心经营约束。[ev_1]

## 三表摘要
利润表显示收入，资产负债表显示权益，现金流量表显示经营现金流，三表摘要对齐报告期并绑定证据。[ev_1]

## 财务分析
财务分析说明收入、权益和经营现金流之间的关系，强调盈利质量、资产安全垫和现金转换能力。该段用于复算报告正文是否具备足够解释深度，并能支持后续估值和风险判断。[ev_1]

## 同行对比
同行对比说明可比公司边界、指标口径和估值差异，不直接套用单一倍数。该段用于检查横向比较是否有明确边界和结论约束。[ev_1]

## 估值观察
估值观察与

## 风险评估
风险太短。

## 投资结论
结论太短。

## 合规披露
本文仅用于系统质量回归和研发验证，不构成投资建议。
""",
        encoding="utf-8",
    )

    result = repair_real_report_artifact(outputs, reports, run_dir=outputs.parent)
    repaired = reports.joinpath("report.md").read_text(encoding="utf-8")

    assert result["changed"] is True
    assert result["before"]["content_depth_blockers"] > result["after"]["content_depth_blockers"]
    assert result["after"]["content_depth_blockers"] == 0
    assert "投资结论维持审慎观察" in repaired
    assert "估值弹性应主要绑定收入增速" in repaired
    assert "估值观察与" not in repaired
    assert outputs.joinpath("real_artifact_remediation.json").exists()


def test_real_artifact_regression_can_repair_before_rescoring(tmp_path):
    source_root = tmp_path / "outputs_user" / "runs"
    outputs = source_root / "amd-thin" / "outputs"
    reports = tmp_path_reports_for_outputs(outputs)
    _write_real_artifact(outputs, symbol="AMD", period="FY2024")
    reports.joinpath("report.md").write_text(
        "# AMD FY2024\n\n## 执行摘要\n短。\n\n## 估值观察\n估值与\n\n## 风险评估\n短。\n\n## 投资结论\n短。\n",
        encoding="utf-8",
    )

    result = run_real_artifact_quality_regression(
        output_root=tmp_path / "real_regression",
        source_roots=[source_root],
        max_per_market=1,
        repair=True,
    )
    rows_path = tmp_path / "real_regression" / result["suite_id"] / "benchmark_runs.jsonl"
    rows = [json.loads(line) for line in rows_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert rows[0]["remediation_changed"] is True
    assert rows[0]["remediation_after_content_depth_blockers"] == 0
    assert outputs.joinpath("real_artifact_remediation.json").exists()


def _write_real_artifact(outputs, *, symbol: str, period: str) -> None:
    reports = tmp_path_reports_for_outputs(outputs)
    outputs.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    report_md = f"""# {symbol} {period} 真实产物回归样本

## 执行摘要
本样本用于真实任务产物复算，内容覆盖业务、三表、估值、风险和投资结论，确保质量评估能读取现有 outputs 与 reports。报告不重新生成，只复用已有产物进行质量门禁计算。[ev_1]

## 业务概览
公司业务覆盖核心产品、客户需求、市场竞争和披露边界。该段用于确保真实产物回归可以识别公司业务画像，并检查报告是否具备用户可读的业务叙事，而不是只展示后端字段。[ev_1]

## 三表摘要
利润表显示收入，资产负债表显示权益，现金流量表显示经营现金流，三表摘要对齐报告期并绑定证据。[ev_1]

## 财务分析
财务分析说明收入、权益和经营现金流之间的关系，强调盈利质量、资产安全垫和现金转换能力。该段用于复算报告正文是否具备足够解释深度，并能支持后续估值和风险判断。[ev_1]

## 同行对比
同行对比说明可比公司边界、指标口径和估值差异，不直接套用单一倍数。该段用于检查横向比较是否有明确边界和结论约束。[ev_1]

## 估值观察
估值观察设置 P/E 为 20x、P/B 为 5x 作为复算样本输入，并说明估值弹性取决于收入增速、现金流质量和风险溢价。正式交付前需要复核真实市值、股本和官方财务口径。[ev_1]

## 风险评估
风险评估覆盖需求波动、竞争加剧、监管变化、现金流承压和估值假设失效，并说明风险如何传导到收入、利润率和估值倍数。该段用于检查真实产物是否存在截断或模板化空话。[ev_1]

## 投资结论
投资结论维持中性评级和审慎观察，基于三表指标完整、业务边界清晰、证据可追溯和估值约束仍需复核。该结论用于真实产物复算，不构成投资建议。[ev_1]

## 合规披露
资料来源：官方披露和结构化财务指标。本文仅用于系统质量回归和研发验证，不构成投资建议；不存在利益冲突。
"""
    outputs.joinpath("run_summary.json").write_text(
        json.dumps({"symbol": symbol, "period": period, "verification_passed": True, "entity_resolution": {"resolved_symbol": symbol, "confidence": 0.95}}, ensure_ascii=False),
        encoding="utf-8",
    )
    outputs.joinpath("claims.json").write_text(json.dumps([{"claim_id": "cl_1", "section_name": "valuation", "claim_text": "估值观察完整。", "evidence_ids": ["ev_1"]}], ensure_ascii=False), encoding="utf-8")
    outputs.joinpath("evidence.json").write_text(json.dumps([{"evidence_id": "ev_1", "source_type": "sec_filing", "trust_level": "official", "title": "Official filing"}], ensure_ascii=False), encoding="utf-8")
    outputs.joinpath("citations.json").write_text(json.dumps([{"evidence_id": "ev_1", "claim_ids": ["cl_1"], "used_in_report": True}], ensure_ascii=False), encoding="utf-8")
    outputs.joinpath("tables.json").write_text(json.dumps([
        {"statement": "income_statement", "metric_name": "revenue", "value": 100, "unit": "亿美元", "period": period},
        {"statement": "balance_sheet", "metric_name": "equity", "value": 80, "unit": "亿美元", "period": period},
        {"statement": "cash_flow_statement", "metric_name": "operating_cash_flow", "value": 20, "unit": "亿美元", "period": period},
    ], ensure_ascii=False), encoding="utf-8")
    outputs.joinpath("financial_metrics.json").write_text(json.dumps({"metrics": []}, ensure_ascii=False), encoding="utf-8")
    outputs.joinpath("charts.json").write_text(json.dumps([{"chart_id": "c1", "title": "chart"}], ensure_ascii=False), encoding="utf-8")
    outputs.joinpath("company_profile_extracted.json").write_text(json.dumps({"business": "sample"}, ensure_ascii=False), encoding="utf-8")
    outputs.joinpath("verification_report.json").write_text(json.dumps({"passed": True, "errors": [], "evidence_gaps": []}, ensure_ascii=False), encoding="utf-8")
    outputs.joinpath("llm_quality_review.json").write_text(json.dumps({"llm_review_pass": True, "total_score": 0.84, "issues": []}, ensure_ascii=False), encoding="utf-8")
    reports.joinpath("report.md").write_text(report_md, encoding="utf-8")
    reports.joinpath("report.html").write_text(f"<html><body>{report_md}</body></html>", encoding="utf-8")


def tmp_path_reports_for_outputs(outputs):
    parts = list(outputs.parts)
    if "outputs_user" in parts:
        parts[parts.index("outputs_user")] = "reports_user"
    if parts[-1] == "outputs":
        parts[-1] = "reports"
    return type(outputs)(*parts)
