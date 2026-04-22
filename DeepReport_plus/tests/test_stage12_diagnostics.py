import json
from pathlib import Path

from src.evaluation.diagnostic_ablation import run_diagnostic_ablation
from src.evaluation.diagnostic_reports import (
    build_metric_sanity_report,
    build_spot_check_root_cause_summary,
    build_spot_check_root_cause_template,
)


def test_stage12_diagnostic_reports_and_ablation(tmp_path: Path):
    eval_root = tmp_path / "eval"
    report_root = tmp_path / "reports"
    case_path = tmp_path / "cases.jsonl"
    eval_root.mkdir(parents=True)
    report_root.mkdir(parents=True)

    claim_table = tmp_path / "claim_table.json"
    claim_table.write_text(
        json.dumps(
            [
                {
                    "claim_id": "cl_1",
                    "claim_text": "Revenue 100.0B, yoy 10.0%",
                    "numeric_values": {"revenue_billion": 100.0, "revenue_growth_pct": 10.0, "gross_margin_pct": 50.0},
                    "evidence_ids": ["x"],
                    "confidence": 0.8,
                }
            ]
        ),
        encoding="utf-8",
    )
    (eval_root / "per_report_metrics.jsonl").write_text(
        json.dumps(
            {
                "case_id": "c1",
                "variant_id": "bm25_real_writer",
                "evidence_coverage": 1.0,
                "current_verifier_pass_ratio": 0.5,
                "reranked_topk_source_types": ["market", "financials", "news"],
                "artifacts": {"claim_table": str(claim_table)},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (eval_root / "per_case_numeric_audit_v1.jsonl").write_text(
        json.dumps(
            {
                "case_id": "c1",
                "variant_id": "bm25_real_writer",
                "numeric_claims": 4,
                "supported_numeric_claims": 3,
                "details": [{"supported": False, "error_type": "value_mismatch", "metric": "revenue"}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    case_path.write_text(
        json.dumps(
            {
                "case_id": "c1",
                "period": "2025Q4",
                "gold_evidence_ids": ["x:2025Q4:financials"],
                "gold_numeric_facts": [
                    {"metric": "revenue", "value": "100.0", "unit": "billion", "period": "2025Q4"},
                    {"metric": "gross_margin", "value": "50.0", "unit": "pct", "period": "2025Q4"},
                    {"metric": "yoy", "value": "10.0", "unit": "pct", "period": "2025Q4"},
                    {"metric": "net_income", "value": "20.0", "unit": "billion", "period": "2025Q4"},
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (report_root / "summary.json").write_text(json.dumps({"sample_count": 1}), encoding="utf-8")
    (report_root / "spot_check_10.csv").write_text(
        "case_id,task_type,claim_grounded_rate,numeric_accuracy,writer_fallback_triggered,error_taxonomy,report_md_path,verification_report_path,claim_table_path\n"
        "c1,financial,0.5,0.75,False,value_mismatch:1,a,b,c\n",
        encoding="utf-8",
    )

    sanity = build_metric_sanity_report(eval_output_root=eval_root, report_root=report_root, eval_case_path=case_path)
    assert Path(sanity["outputs"]["metric_sanity_report_md"]).exists()
    template = build_spot_check_root_cause_template(report_root=report_root)
    assert Path(template["spot_check_root_cause_template_csv"]).exists()
    summary_template = build_spot_check_root_cause_summary(report_root=report_root)
    assert Path(summary_template["spot_check_root_cause_frequency_json"]).exists()
    cmp_result = run_diagnostic_ablation(
        eval_output_root=eval_root,
        baseline_report_root=report_root,
        eval_case_path=case_path,
        output_root=tmp_path / "diag",
        run_id="test_run",
    )
    assert Path(cmp_result["outputs"]["comparison_md"]).exists()
