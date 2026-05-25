import json

from src.evaluation.benchmark_metrics import (
    ARTIFACT_DERIVED_TRACE_LABEL,
    evaluate_existing_run,
    failure_categories,
    summarize_records,
    traceable_claim_metrics,
    write_benchmark_outputs,
)


def test_existing_run_metrics_use_deterministic_gate_and_traceable_claims(tmp_path):
    outputs, reports = _write_complete_run(tmp_path, symbol="AMD")
    (outputs / "delivery_gate.json").write_text(
        json.dumps({"delivery_pass": False, "llm_review_pass": False}),
        encoding="utf-8",
    )

    result = evaluate_existing_run(
        outputs,
        case={"case_id": "quick9_us_amd", "market": "US", "company_name": "AMD", "canonical_symbol": "AMD"},
        reports_dir=reports,
    )

    assert result["status"] == "evaluated"
    assert result["delivery_pass"] is True
    assert result["existing_three_layer_delivery_pass"] is False
    assert result["objective_quality_score"] == 91.0
    assert result["traceable_claim_rate"] == 1.0
    assert result["critical_claim_count"] == 1


def test_traceable_claim_rate_fails_numeric_claim_with_explicit_missing_lineage():
    result = traceable_claim_metrics(
        claims=[
            {
                "claim_id": "cl_fin",
                "section_name": "financial_statements",
                "claim_text": "收入为 100。",
                "evidence_ids": ["ev_1"],
                "numeric_values": {"revenue": 100},
                "metric_lineage_ids": [],
            }
        ],
        evidence=[{"evidence_id": "ev_1"}],
        citations=[{"evidence_id": "ev_1", "claim_ids": ["cl_fin"], "used_in_report": True}],
        report_text="收入为 100。[ev_1]",
    )

    assert result["label"] == ARTIFACT_DERIVED_TRACE_LABEL
    assert result["critical_claim_count"] == 1
    assert result["traceable_claim_count"] == 0
    assert result["rate"] == 0.0
    assert result["issues"][0]["reason"] == "numeric_lineage_missing"


def test_traceable_claim_requires_explicit_used_in_report_flag():
    result = traceable_claim_metrics(
        claims=[{"claim_id": "cl_risk", "section_name": "risk", "evidence_ids": ["ev_1"]}],
        evidence=[{"evidence_id": "ev_1"}],
        citations=[{"evidence_id": "ev_1", "claim_ids": ["cl_risk"], "used_in_report": False}],
        report_text="Risk conclusion cites [ev_1] in text only.",
    )

    assert result["critical_claim_count"] == 1
    assert result["rate"] == 0.0
    assert result["issues"][0]["reason"] == "citation_not_used_in_report"


def test_traceable_claim_validates_lineage_against_existing_financial_metrics():
    result = traceable_claim_metrics(
        claims=[
            {
                "claim_id": "cl_fin",
                "section_name": "financial_analysis",
                "evidence_ids": ["ev_1"],
                "numeric_values": {"revenue": 100},
                "metric_lineage_ids": ["missing_metric"],
            }
        ],
        evidence=[{"evidence_id": "ev_1"}],
        citations=[{"evidence_id": "ev_1", "claim_ids": ["cl_fin"], "used_in_report": True}],
        report_text="Revenue is supported.",
        financial_metrics={"metrics": [{"metric_lineage_id": "available_metric"}]},
    )

    assert result["rate"] == 0.0
    assert result["issues"][0]["reason"] == "numeric_lineage_missing"


def test_traceable_claim_rate_is_zero_when_no_critical_claim_candidates():
    result = traceable_claim_metrics(
        claims=[{"claim_id": "cl_profile", "section_name": "business_profile", "evidence_ids": ["ev_1"]}],
        evidence=[{"evidence_id": "ev_1"}],
        citations=[{"evidence_id": "ev_1", "claim_ids": ["cl_profile"], "used_in_report": True}],
        report_text="Profile description.",
    )

    assert result["critical_claim_count"] == 0
    assert result["rate"] == 0.0
    assert result["issues"] == [{"claim_id": "", "reason": "no_critical_claim_candidates"}]


def test_existing_run_with_missing_base_artifacts_is_not_evaluable(tmp_path):
    outputs = tmp_path / "run" / "outputs"
    reports = tmp_path / "run" / "reports"
    outputs.mkdir(parents=True)
    reports.mkdir(parents=True)
    (reports / "report.md").write_text("# report", encoding="utf-8")

    result = evaluate_existing_run(
        outputs,
        case={"case_id": "case", "market": "US", "company_name": "Apple", "canonical_symbol": "AAPL"},
        reports_dir=reports,
    )

    assert result["status"] == "not_evaluable"
    assert result["objective_quality_score"] is None
    assert "claims.json" in result["missing_artifacts"]


def test_existing_run_recomputes_objective_quality_when_quality_report_is_missing(tmp_path, monkeypatch):
    outputs, reports = _write_complete_run(tmp_path, symbol="AMD")
    (outputs / "quality_report.json").unlink()

    monkeypatch.setattr(
        "src.evaluation.benchmark_metrics.evaluate_report_quality_from_paths",
        lambda *_args, **_kwargs: {
            "total_score": 0.88,
            "issue_counts": {"fatal": 0, "blocker": 0},
            "required_checks": {
                "details": {
                    "non_empty_executive_summary": True,
                    "non_empty_risk": True,
                    "non_empty_investment_conclusion": True,
                    "has_three_table_summary": True,
                    "valuation_or_reason": True,
                }
            },
        },
    )

    result = evaluate_existing_run(
        outputs,
        case={"case_id": "quick9_us_amd", "market": "US", "company_name": "AMD", "canonical_symbol": "AMD"},
        reports_dir=reports,
    )

    assert result["objective_quality_score"] == 88.0
    assert result["objective_quality_source"] == "recomputed_read_only"


def test_existing_run_records_deterministic_delivery_failure(tmp_path):
    outputs, reports = _write_complete_run(tmp_path, symbol="AMD")
    (outputs / "chart_consistency.json").write_text(json.dumps({"passed": False}), encoding="utf-8")

    result = evaluate_existing_run(
        outputs,
        case={"case_id": "quick9_us_amd", "market": "US", "company_name": "AMD", "canonical_symbol": "AMD"},
        reports_dir=reports,
    )

    assert result["status"] == "evaluated"
    assert result["delivery_pass"] is False
    assert result["delivery_checks"]["chart_no_serious_conflict"] is False
    assert "chart_text_mismatch" in result["failure_categories"]


def test_delivery_metric_does_not_duplicate_objective_quality_blockers(tmp_path):
    outputs, reports = _write_complete_run(tmp_path, symbol="AMD")
    quality = json.loads((outputs / "quality_report.json").read_text(encoding="utf-8"))
    quality["issue_counts"] = {"fatal": 0, "blocker": 1}
    quality["issues"] = [{"severity": "blocker", "message": "pre_write_critic_passed"}]
    (outputs / "quality_report.json").write_text(json.dumps(quality), encoding="utf-8")

    result = evaluate_existing_run(
        outputs,
        case={"case_id": "quick9_us_amd", "market": "US", "company_name": "AMD", "canonical_symbol": "AMD"},
        reports_dir=reports,
    )

    assert result["delivery_pass"] is True
    assert result["delivery_checks"]["no_objective_fatal_or_blocker"] is False
    assert "quality_gate_blocker" in result["failure_categories"]


def test_delivery_metric_accepts_explicit_three_statement_gap_disclosure(tmp_path):
    outputs, reports = _write_complete_run(tmp_path, symbol="0700.HK")
    report = (reports / "report.md").read_text(encoding="utf-8")
    report = report.replace(
        "利润表、资产负债表和现金流量表均已覆盖。",
        "三表缺口：利润表、资产负债表和现金流量表尚未完整形成可引用证据。",
    )
    (reports / "report.md").write_text(report, encoding="utf-8")
    quality = json.loads((outputs / "quality_report.json").read_text(encoding="utf-8"))
    quality["required_checks"]["details"]["has_three_table_summary"] = False
    (outputs / "quality_report.json").write_text(json.dumps(quality), encoding="utf-8")

    result = evaluate_existing_run(
        outputs,
        case={"case_id": "quick9_hk_tencent", "market": "HK", "company_name": "腾讯控股", "canonical_symbol": "0700.HK"},
        reports_dir=reports,
    )

    assert result["delivery_pass"] is True
    assert result["delivery_checks"]["three_statements_or_disclosed_gap"] is True


def test_failure_taxonomy_reads_actual_issue_messages_not_unrelated_metadata():
    checks = {
        "identity_resolved": True,
        "three_statements_or_disclosed_gap": True,
        "valuation_or_reason": True,
        "citations_in_body": True,
        "critical_claims_traceable": True,
        "chart_no_serious_conflict": True,
        "no_objective_fatal_or_blocker": True,
        "verifier_passed": True,
    }

    result = failure_categories(
        checks,
        quality={"artifact_counts": {"pdf_sections": 0}, "generalization_checks": {"missing": True}, "issues": []},
        verification={"errors": [], "warnings": []},
    )

    assert result == []


def test_summary_and_report_keep_not_run_out_of_metric_denominator(tmp_path):
    rows = [
        {
            "case_id": "a",
            "market": "US",
            "canonical_symbol": "AAPL",
            "status": "evaluated",
            "delivery_pass": True,
            "objective_quality_score": 90.0,
            "traceable_claim_rate": 0.75,
            "failure_categories": [],
        },
        {
            "case_id": "b",
            "market": "HK",
            "canonical_symbol": "0700.HK",
            "status": "not_run",
            "failure_categories": [],
        },
    ]

    summary = summarize_records(rows, total_case_count=2)
    paths = write_benchmark_outputs(tmp_path / "results", rows, summary)

    assert summary["observed_run_count"] == 1
    assert summary["overall"]["delivery_pass_rate"] == 1.0
    assert summary["overall"]["objective_quality_score"] == 90.0
    report = open(paths["benchmark_report"], encoding="utf-8").read()
    assert "observed_runs=1/2" in report
    assert "not a completed quick-9 rerun or a baseline comparison" in report
    assert "denominators include evaluated runs only" in report


def _write_complete_run(tmp_path, symbol):
    outputs = tmp_path / "run" / "outputs"
    reports = tmp_path / "run" / "reports"
    outputs.mkdir(parents=True)
    reports.mkdir(parents=True)
    report = """
# AMD 公司研报
## 执行摘要
收入和现金流支持中性结论。[ev_1]
## 主营业务
业务范围清晰。
## 三表摘要
利润表、资产负债表和现金流量表均已覆盖。
## 估值观察
P/E 为 20x。
## 风险提示
风险包括竞争压力。
## 投资结论
基于现金流和估值，维持中性。
"""
    (reports / "report.md").write_text(report, encoding="utf-8")
    artifacts = {
        "run_summary.json": {
            "symbol": symbol,
            "period": "2026Q1",
            "entity_resolution": {"resolved_symbol": symbol},
        },
        "claims.json": [
            {
                "claim_id": "cl_fin",
                "section_name": "financial_statements",
                "claim_text": "收入和现金流支持结论。",
                "evidence_ids": ["ev_1"],
                "numeric_values": {"revenue": 100},
                "metric_lineage_ids": ["metric_1"],
            }
        ],
        "evidence.json": [{"evidence_id": "ev_1"}],
        "citations.json": [{"evidence_id": "ev_1", "claim_ids": ["cl_fin"], "used_in_report": True}],
        "verification_report.json": {"passed": True},
        "chart_consistency.json": {"passed": True},
        "quality_report.json": {
            "total_score": 0.91,
            "issue_counts": {"fatal": 0, "blocker": 0},
            "required_checks": {
                "details": {
                    "non_empty_executive_summary": True,
                    "non_empty_risk": True,
                    "non_empty_investment_conclusion": True,
                    "has_three_table_summary": True,
                    "valuation_or_reason": True,
                }
            },
        },
    }
    for name, payload in artifacts.items():
        (outputs / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return outputs, reports
