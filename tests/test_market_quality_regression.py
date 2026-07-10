import json

from src.evaluation.benchmark_summary_importer import load_benchmark_summaries
from src.evaluation.market_quality_regression import run_market_quality_regression


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
