from pathlib import Path

import pytest

from src.evaluation.local_correction_v1 import run_local_correction_v1


def test_local_correction_v1_outputs_exist():
    out_root = Path("reports/local_correction_v1")
    run_id = "test_local_fix_v1"
    required_inputs = [
        Path("reports/eval_v1_diagnostics/diag_20260418_cn_final/spot_check_10_root_cause_template.csv"),
        Path("data/evaluation/eval_v1"),
        Path("data/eval_v1/cases.jsonl"),
        Path("reports/eval_v1_diagnostics/diag_20260418_cn_final/verifier_threshold_scan/threshold_scan.json"),
    ]
    missing = [path for path in required_inputs if not path.exists()]
    if missing:
        pytest.skip("optional historical eval fixtures are not present: " + ", ".join(str(path) for path in missing))
    idx = run_local_correction_v1(
        template_csv_path=required_inputs[0],
        eval_output_root=required_inputs[1],
        eval_case_path=required_inputs[2],
        threshold_scan_json=required_inputs[3],
        output_root=out_root,
        primary_variant="bm25_real_writer",
        run_id=run_id,
    )
    run_dir = out_root / idx["run_id"]
    assert (run_dir / "run_index.json").exists()
    assert (run_dir / "spot_check_root_cause_summary" / "spot_check_root_cause_summary.json").exists()
    assert (run_dir / "verifier_calibration_fix" / "summary.json").exists()
    assert (run_dir / "numeric_collision_fix" / "summary.json").exists()
