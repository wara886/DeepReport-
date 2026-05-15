from pathlib import Path

from scripts.run_memory_ablation import build_memory_ablation_config, render_memory_ablation_markdown, summarize_memory_ablation


def test_build_memory_ablation_config_creates_two_memory_variants(tmp_path: Path):
    config = build_memory_ablation_config(
        {
            "evaluation": {
                "max_samples": 1,
                "multi_agent": {
                    "model_config_path": "configs/model_backends.yaml",
                    "variants": [
                        {
                            "id": "dynamic_fast",
                            "execution_mode": "dynamic",
                            "fast": True,
                            "engines": ["local_real_data"],
                            "retrieval_ranking_mode": "hybrid_rerank",
                        }
                    ],
                },
            }
        },
        output_root=tmp_path / "out",
    )

    variants = config["evaluation"]["multi_agent"]["variants"]
    assert [variant["id"] for variant in variants] == ["memory_enabled", "memory_disabled"]
    assert variants[0]["memory_enabled"] is True
    assert variants[1]["memory_enabled"] is False
    assert variants[0]["execution_mode"] == "dynamic"
    assert variants[0]["retrieval_ranking_mode"] == "hybrid_rerank"
    assert "memory_enabled_store" in variants[0]["memory_root"]


def test_summarize_memory_ablation_promotes_when_quality_improves_and_latency_is_bounded():
    comparison = summarize_memory_ablation(
        report_rows=[
            _report_row("memory_disabled", verifier=False, duration=10.0, checklist=0.5, coverage=0.8),
            _report_row("memory_enabled", verifier=True, duration=20.0, checklist=1.0, coverage=1.0),
        ],
        numeric_rows=[
            _numeric_row("memory_disabled", supported=8, unsupported=2),
            _numeric_row("memory_enabled", supported=10, unsupported=0),
        ],
        latency_tolerance_sec=15.0,
    )

    assert comparison["decision"] == "promote_memory"
    assert comparison["quality_guard_passed"] is True
    assert comparison["latency_guard_passed"] is True
    assert comparison["deltas"]["verification_pass_rate"] == 1.0
    assert comparison["deltas"]["numeric_accuracy"] == 0.2
    assert "decision: promote_memory" in render_memory_ablation_markdown(comparison)


def test_summarize_memory_ablation_holds_when_latency_is_too_high():
    comparison = summarize_memory_ablation(
        report_rows=[
            _report_row("memory_disabled", verifier=True, duration=10.0, checklist=1.0, coverage=1.0),
            _report_row("memory_enabled", verifier=True, duration=70.0, checklist=1.0, coverage=1.0),
        ],
        numeric_rows=[
            _numeric_row("memory_disabled", supported=10, unsupported=0),
            _numeric_row("memory_enabled", supported=10, unsupported=0),
        ],
        latency_tolerance_sec=15.0,
    )

    assert comparison["decision"] == "hold_memory"
    assert comparison["quality_guard_passed"] is True
    assert comparison["latency_guard_passed"] is False
    assert comparison["deltas"]["latency_delta_sec"] == 60.0


def test_summarize_memory_ablation_rejects_quality_regression():
    comparison = summarize_memory_ablation(
        report_rows=[
            _report_row("memory_disabled", verifier=True, duration=10.0, checklist=1.0, coverage=1.0),
            _report_row("memory_enabled", verifier=False, duration=12.0, checklist=0.8, coverage=0.9),
        ],
        numeric_rows=[
            _numeric_row("memory_disabled", supported=10, unsupported=0),
            _numeric_row("memory_enabled", supported=9, unsupported=1),
        ],
        latency_tolerance_sec=15.0,
    )

    assert comparison["decision"] == "reject_memory"
    assert comparison["quality_guard_passed"] is False
    assert "verification_pass_rate" in comparison["regressions"]
    assert "numeric_accuracy" in comparison["regressions"]


def _report_row(
    variant_id: str,
    verifier: bool,
    duration: float,
    checklist: float,
    coverage: float,
):
    return {
        "variant_id": variant_id,
        "rule_verifier_passed": verifier,
        "evidence_coverage": coverage,
        "evidence_alignment": coverage,
        "chart_consistency_passed": verifier,
        "contest_checklist_pass_rate": checklist,
        "total_duration_sec": duration,
    }


def _numeric_row(variant_id: str, supported: int, unsupported: int):
    return {
        "variant_id": variant_id,
        "case_id": f"case_{variant_id}",
        "numeric_claims": supported + unsupported,
        "supported_numeric_claims": supported,
        "unsupported_numeric_claims": unsupported,
        "error_breakdown": {
            "value_mismatch": unsupported,
            "unit_mismatch": 0,
            "period_mismatch": 0,
            "unsupported_number": 0,
            "hallucinated_number": 0,
        },
        "details": [],
    }
