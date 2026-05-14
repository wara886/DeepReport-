import json
from pathlib import Path

import pytest

from src.eval.metrics import (
    aggregate_metrics,
    artifact_generation_pass,
    compute_case_metrics,
    count_citations,
    numeric_audit_pass_rate,
    required_sections_coverage,
    task_completion_rate,
)
from src.eval.schema import EvalCase


def _case():
    return EvalCase(
        case_id="case_001",
        symbol="AAPL",
        market="US",
        period="2025Q4",
        topic="基本面、估值、风险",
        report_type="company_research",
        required_sections=["business_overview", "financials", "valuation", "risks", "peer_comparison"],
        required_source_types=["financials", "filing"],
        difficulty="normal",
        tags=["phase0"],
    )


def test_required_sections_coverage_supports_aliases():
    markdown = """
# Report

## Business Overview

## Financial Analysis

## 估值观察

## 风险评估

## Peer Comparison
"""

    assert required_sections_coverage(markdown, _case().required_sections) == 1.0


def test_required_sections_coverage_returns_partial_ratio():
    markdown = "# Report\n\n## Business Overview\n\n## Financial Analysis\n"

    assert required_sections_coverage(markdown, _case().required_sections) == 0.4


def test_artifact_generation_pass_requires_core_files(tmp_path: Path):
    report_md = tmp_path / "report.md"
    report_json = tmp_path / "report.json"
    verification = tmp_path / "verification_report.json"
    report_md.write_text("# Report", encoding="utf-8")
    report_json.write_text("{}", encoding="utf-8")
    verification.write_text('{"passed": true}', encoding="utf-8")

    assert artifact_generation_pass({"report_md": report_md, "report_json": report_json, "verification_report": verification}) is True


def test_compute_case_metrics_from_artifacts(tmp_path: Path):
    reports = tmp_path / "reports"
    outputs = tmp_path / "outputs"
    reports.mkdir()
    outputs.mkdir()
    (reports / "report.md").write_text(
        "# Report\n\n## Business Overview\n\n## Financial Analysis\n\n## Valuation\n\n## Risks\n\n## Peer Comparison\n\nAAPL revenue grew. [ev1]",
        encoding="utf-8",
    )
    (reports / "report.json").write_text("{}", encoding="utf-8")
    (outputs / "verification_report.json").write_text(json.dumps({"passed": True}), encoding="utf-8")
    (outputs / "claims.json").write_text(json.dumps([{"claim_text": "AAPL revenue grew.", "evidence_ids": ["ev1"]}]), encoding="utf-8")
    (outputs / "evidence.json").write_text(json.dumps([{"evidence_id": "ev1"}]), encoding="utf-8")
    (outputs / "citations.json").write_text(json.dumps([{"evidence_id": "ev1"}]), encoding="utf-8")
    (outputs / "run_summary.json").write_text(json.dumps({"total_duration_sec": 1.25}), encoding="utf-8")

    metrics = compute_case_metrics(
        _case(),
        {
            "artifacts": {
                "report_md": str(reports / "report.md"),
                "report_json": str(reports / "report.json"),
                "verification_report": str(outputs / "verification_report.json"),
                "claims": str(outputs / "claims.json"),
                "evidence": str(outputs / "evidence.json"),
                "citations": str(outputs / "citations.json"),
                "run_summary": str(outputs / "run_summary.json"),
            }
        },
    )

    assert metrics["task_completion_rate"] == 1.0
    assert metrics["artifact_generation_pass"] is True
    assert metrics["verification_pass"] is True
    assert metrics["claim_count"] == 1
    assert metrics["evidence_count"] == 1
    assert metrics["citation_count"] == 1
    assert metrics["total_latency_sec"] == 1.25
    assert metrics["citation_support_rate"] is None
    assert "TODO" in metrics["unsupported_metric_todos"][0]


def test_aggregate_metrics_summarizes_rows():
    summary = aggregate_metrics(
        [
            {"task_completion_rate": 1.0, "required_sections_coverage": 1.0, "artifact_generation_pass": True, "verification_pass": True, "claim_count": 2, "evidence_count": 3, "citation_count": 4, "total_latency_sec": 2.0},
            {"task_completion_rate": 0.0, "required_sections_coverage": 0.5, "artifact_generation_pass": False, "verification_pass": False, "claim_count": 0, "evidence_count": 1, "citation_count": 0, "total_latency_sec": 4.0},
        ]
    )

    assert summary["case_count"] == 2
    assert summary["task_completion_rate"] == 0.5
    assert summary["required_sections_coverage"] == 0.75
    assert summary["total_latency_sec_sum"] == 6.0


def test_placeholder_metrics_raise_not_implemented():
    with pytest.raises(NotImplementedError, match="TODO"):
        numeric_audit_pass_rate()


def test_citation_counter_falls_back_to_markdown_pattern():
    assert count_citations([], "Revenue grew [ev1] and margin improved [AAPL:2025Q4:financials].") == 2


def test_task_completion_rate_requires_all_gates():
    assert task_completion_rate(True, 1.0, True) == 1.0
    assert task_completion_rate(True, 0.8, True) == 0.0
