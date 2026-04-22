import json
from pathlib import Path

from src.evaluation.summarize_eval_v1 import build_regression_v1_outputs


def test_build_regression_v1_outputs(tmp_path: Path):
    eval_root = tmp_path / "eval"
    eval_root.mkdir(parents=True)
    case_path = tmp_path / "cases.jsonl"
    report_root = tmp_path / "reports"

    (eval_root / "per_report_metrics.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "case_id": "c1",
                        "variant_id": "bm25_real_writer",
                        "task_type": "financial",
                        "evidence_coverage": 1.0,
                        "current_verifier_pass_ratio": 0.8,
                        "writer_fallback_triggered": False,
                        "writer_error_message": "",
                        "reranked_topk_ids": ["id_financials", "id_news"],
                    }
                )
            ]
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
                "error_breakdown": {
                    "value_mismatch": 1,
                    "unit_mismatch": 0,
                    "period_mismatch": 0,
                    "unsupported_number": 0,
                    "hallucinated_number": 0,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    case_path.write_text(
        json.dumps(
            {
                "case_id": "c1",
                "gold_evidence_ids": ["x:2025Q4:financials"],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = build_regression_v1_outputs(
        eval_output_root=eval_root,
        eval_case_path=case_path,
        report_root=report_root,
        primary_variant="bm25_real_writer",
    )
    assert summary["sample_count"] == 1
    assert summary["numeric_accuracy"] == 0.75
    assert summary["top1_evidence_hit_rate"] == 1.0
    assert (report_root / "summary.json").exists()
    assert (report_root / "summary.md").exists()
    assert (report_root / "per_case.csv").exists()

