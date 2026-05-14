import json
from pathlib import Path

from src.eval.evaluator import BaselineEvaluator
from src.eval.schema import EvalCase


def _case(case_id="case_001"):
    return EvalCase(
        case_id=case_id,
        symbol="AAPL",
        market="US",
        period="2025Q4",
        topic="基本面、估值、风险",
        report_type="company_research",
        required_sections=["business_overview", "financials"],
        required_source_types=["financials"],
        difficulty="normal",
        tags=["phase0"],
    )


def _adapter(case: EvalCase, case_root: Path):
    reports = case_root / "reports"
    outputs = case_root / "outputs"
    reports.mkdir(parents=True)
    outputs.mkdir(parents=True)
    (reports / "report.md").write_text("# Report\n\n## Business Overview\n\n## Financial Analysis\n\nRevenue grew. [ev1]", encoding="utf-8")
    (reports / "report.json").write_text("{}", encoding="utf-8")
    (outputs / "verification_report.json").write_text(json.dumps({"passed": True}), encoding="utf-8")
    (outputs / "claims.json").write_text(json.dumps([{"claim_text": "Revenue grew.", "evidence_ids": ["ev1"]}]), encoding="utf-8")
    (outputs / "evidence.json").write_text(json.dumps([{"evidence_id": "ev1"}]), encoding="utf-8")
    (outputs / "citations.json").write_text(json.dumps([{"evidence_id": "ev1"}]), encoding="utf-8")
    (outputs / "run_summary.json").write_text(json.dumps({"total_duration_sec": 0.5}), encoding="utf-8")
    return {
        "status": "completed",
        "artifacts": {
            "report_md": str(reports / "report.md"),
            "report_json": str(reports / "report.json"),
            "verification_report": str(outputs / "verification_report.json"),
            "claims": str(outputs / "claims.json"),
            "evidence": str(outputs / "evidence.json"),
            "citations": str(outputs / "citations.json"),
            "run_summary": str(outputs / "run_summary.json"),
        },
    }


def test_baseline_evaluator_writes_single_case_outputs(tmp_path: Path):
    evaluator = BaselineEvaluator({"baseline_test": _adapter})

    summary = evaluator.run([_case()], baseline_id="baseline_test", output_root=tmp_path, run_id="run_single")

    run_root = tmp_path / "run_single"
    assert summary["metrics"]["case_count"] == 1
    assert summary["metrics"]["task_completion_rate"] == 1.0
    assert (run_root / "eval_summary.json").exists()
    assert (run_root / "per_case_metrics.jsonl").exists()
    assert (run_root / "baseline_comparison.json").exists()
    assert (run_root / "failure_cases.jsonl").exists()
    assert (run_root / "failure_cases.jsonl").read_text(encoding="utf-8") == ""


def test_baseline_evaluator_writes_multi_case_outputs(tmp_path: Path):
    evaluator = BaselineEvaluator({"baseline_test": _adapter})

    summary = evaluator.run([_case("case_001"), _case("case_002")], baseline_id="baseline_test", output_root=tmp_path, run_id="run_batch")

    rows = (tmp_path / "run_batch" / "per_case_metrics.jsonl").read_text(encoding="utf-8").splitlines()
    comparison = json.loads((tmp_path / "run_batch" / "baseline_comparison.json").read_text(encoding="utf-8"))
    assert summary["metrics"]["case_count"] == 2
    assert len(rows) == 2
    assert comparison["baselines"]["baseline_test"]["task_completion_rate"] == 1.0
