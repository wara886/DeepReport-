import json

from src.evaluation.generalization_regression import run_generalization_regression, select_regression_cases


def test_generalization_regression_uses_sentinels_plus_random_pool():
    cases = select_regression_cases(random_count=3, seed=11)
    keys = {(case.symbol, case.period) for case in cases}

    assert ("600519.SS", "2025Q4") in keys
    assert ("AMD", "2025Q4") in keys
    assert ("0700.HK", "LATEST") in keys
    assert len(cases) == 6
    assert len({case.bucket for case in cases}) >= 4


def test_generalization_regression_selection_is_deterministic():
    first = [case.to_dict() for case in select_regression_cases(random_count=4, seed=3)]
    second = [case.to_dict() for case in select_regression_cases(random_count=4, seed=3)]

    assert first == second


def test_generalization_regression_blocks_when_deepseek_preflight_fails(tmp_path, monkeypatch):
    def fake_preflight(require_deepseek=True, config_path="configs/data_sources.yaml"):
        return {
            "schema_version": "generalization_regression_preflight.v1",
            "status": "blocked",
            "blocked_reason": "deepseek_unavailable",
            "deepseek_required": require_deepseek,
            "deepseek_ok": False,
            "runtime_source_health": {"model": {"deepseek": {"ok": False}}},
        }

    monkeypatch.setattr("src.evaluation.generalization_regression.run_regression_preflight", fake_preflight)

    summary = run_generalization_regression(output_root=tmp_path, random_count=1)

    assert summary["status"] == "blocked"
    assert summary["blocked_reason"] == "deepseek_unavailable"
    assert summary["case_count"] == 0
    saved = json.loads((tmp_path / "generalization_regression_summary.json").read_text(encoding="utf-8"))
    assert saved["status"] == "blocked"
