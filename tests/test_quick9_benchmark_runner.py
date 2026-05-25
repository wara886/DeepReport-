import json
from pathlib import Path

from scripts.run_quick9_multi_agent_benchmark import (
    _apply_source_failure_taxonomy,
    _primary_blocker,
    load_quick9_config,
    reassess_quick9_existing_artifacts,
    run_quick9_multi_agent_benchmark,
)


def test_repository_quick9_config_fixes_nine_multi_agent_cases():
    benchmark = load_quick9_config("configs/benchmark_quick9_multi_agent.yaml")

    assert len(benchmark["cases"]) == 9
    assert {case["market"] for case in benchmark["cases"]} == {"US", "HK", "CN-A"}
    assert benchmark["execution"]["variant"] == "multi_agent"
    assert benchmark["execution"]["target_period"] == "2026Q1"


def test_repair_config_keeps_fixed_cases_and_enables_pre_phase3_repairs():
    benchmark = load_quick9_config("configs/benchmark_quick9_multi_agent_repair.yaml")

    assert len(benchmark["cases"]) == 9
    assert benchmark["execution"]["repair_evaluation"] is True
    assert benchmark["execution"]["execution_mode"] == "diagnostic_full"
    assert benchmark["execution"]["max_rework_rounds"] == 1
    assert "hkex_announcements" in benchmark["execution"]["engines_by_market"]["HK"]
    assert "eastmoney" not in benchmark["execution"]["engines_by_market"]["CN-A"]


def test_runner_uses_fixed_denominator_and_records_runtime_failures(tmp_path, monkeypatch):
    config = tmp_path / "benchmark.yaml"
    config.write_text(
        """
benchmark:
  execution:
    variant: multi_agent
    target_period: 2026Q1
    execution_mode: collaborative
    fast: true
    enable_remote_data: false
    engines_by_market:
      US: [local_real_data]
      HK: [local_real_data]
      CN-A: [local_real_data]
  cases:
    - {case_id: us, market: US, company_name: Apple, canonical_symbol: AAPL}
    - {case_id: hk, market: HK, company_name: Tencent, canonical_symbol: 0700.HK}
    - {case_id: cna, market: CN-A, company_name: Moutai, canonical_symbol: 600519.SS}
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "scripts.run_quick9_multi_agent_benchmark.run_delivery_quality_pipeline",
        _write_quality_pipeline_artifacts,
    )

    summary = run_quick9_multi_agent_benchmark(
        config_path=config,
        output_root=tmp_path / "results",
        orchestrator_factory=FakeOrchestrator,
        run_stamp="fixed",
    )

    assert summary["case_count"] == 3
    assert summary["overall"]["delivery_pass_rate"] == round(2 / 3, 4)
    assert summary["overall"]["traceable_claim_rate"] == round(2 / 3, 4)
    assert summary["overall"]["objective_quality_score"] == 90.0
    hk = next(row for row in summary["records"] if row["market"] == "HK")
    assert hk["status"] == "failed"
    assert hk["failure_categories"] == ["runtime_or_model_failure"]
    assert (tmp_path / "results" / "market_breakdown.csv").exists()
    report = (tmp_path / "results" / "benchmark_report.md").read_text(encoding="utf-8")
    assert "No `Direct LLM` or `Single-Agent RAG` baseline was run" in report


def test_repair_runner_calls_existing_delivery_rework_loop(tmp_path, monkeypatch):
    config = tmp_path / "benchmark.yaml"
    config.write_text(
        """
benchmark:
  execution:
    variant: multi_agent
    repair_evaluation: true
    target_period: 2026Q1
    execution_mode: diagnostic_full
    max_rework_rounds: 1
    fast: true
    enable_remote_data: false
    engines_by_market:
      US: [local_real_data]
  cases:
    - {case_id: us, market: US, company_name: Apple, canonical_symbol: AAPL}
""".strip(),
        encoding="utf-8",
    )
    called = []

    monkeypatch.setattr(
        "scripts.run_quick9_multi_agent_benchmark.run_delivery_quality_pipeline",
        _write_quality_pipeline_artifacts,
    )

    def fake_rework_loop(**kwargs):
        called.append(kwargs["max_rounds"])
        return {"rounds": [{"round": 1}], "reworked": True, "quality_result": kwargs["initial_quality_result"]}

    monkeypatch.setattr("scripts.run_quick9_multi_agent_benchmark.run_delivery_rework_loop", fake_rework_loop)

    summary = run_quick9_multi_agent_benchmark(
        config_path=config,
        output_root=tmp_path / "results",
        orchestrator_factory=FakeOrchestrator,
        run_stamp="repair",
    )

    assert called == [1]
    assert summary["reworked_case_count"] == 1
    report = (tmp_path / "results" / "benchmark_report.md").read_text(encoding="utf-8")
    assert "Phase 2R - Pre-Phase-3 Repair Evaluation" in report


def test_reassessment_reuses_recorded_artifacts_without_rerunning_agents(tmp_path, monkeypatch):
    config = tmp_path / "benchmark.yaml"
    config.write_text(
        """
benchmark:
  execution:
    variant: multi_agent
    target_period: 2026Q1
    execution_mode: collaborative
    fast: true
    enable_remote_data: false
    engines_by_market:
      US: [local_real_data]
  cases:
    - {case_id: us, market: US, company_name: Apple, canonical_symbol: AAPL}
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "scripts.run_quick9_multi_agent_benchmark.run_delivery_quality_pipeline",
        _write_quality_pipeline_artifacts,
    )
    recorded_root = tmp_path / "recorded"
    run_quick9_multi_agent_benchmark(
        config_path=config,
        output_root=recorded_root,
        orchestrator_factory=FakeOrchestrator,
        run_stamp="recorded",
    )
    recorded_path = recorded_root / "benchmark_runs.jsonl"
    recorded = json.loads(recorded_path.read_text(encoding="utf-8").strip())
    recorded["delivery_pass"] = False
    recorded_path.write_text(json.dumps(recorded) + "\n", encoding="utf-8")

    summary = reassess_quick9_existing_artifacts(
        config_path=config,
        source_output_root=recorded_root,
        output_root=tmp_path / "reassessed",
    )

    assert summary["overall"]["delivery_pass_rate"] == 1.0
    assert summary["records"][0]["reassessed_from_recorded_run"] is True
    report = (tmp_path / "reassessed" / "benchmark_report.md").read_text(encoding="utf-8")
    assert "Read-only Contract Reassessment" in report
    assert "No agents or remote sources were invoked" in report


def test_actionable_source_failure_is_taxonomy_not_primary_when_gate_gap_is_known():
    row = _apply_source_failure_taxonomy(
        {
            "delivery_pass": False,
            "failure_categories": ["citation_or_evidence_gap", "quality_gate_blocker"],
            "source_failure_reasons": ["eastmoney: fetch_error", "local_evidence: no_records_for_symbol_period"],
        }
    )

    assert "source_access_or_fetch" in row["failure_categories"]
    assert _primary_blocker(row["failure_categories"]) == "citation_or_evidence_gap"


class FakeOrchestrator:
    def __init__(self, output_dir, report_dir, **_kwargs):
        self.outputs = Path(output_dir)
        self.reports = Path(report_dir)

    def run(self, symbol, period, **_kwargs):
        if symbol == "0700.HK":
            raise RuntimeError("source unavailable")
        self.outputs.mkdir(parents=True, exist_ok=True)
        self.reports.mkdir(parents=True, exist_ok=True)
        self.reports.joinpath("report.md").write_text("# Report", encoding="utf-8")
        artifacts = {
            "run_summary.json": {"symbol": symbol, "period": period, "model": "fake", "entity_resolution": {"resolved_symbol": symbol}},
            "claims.json": [{"claim_id": "cl_1", "section_name": "risk", "evidence_ids": ["ev_1"]}],
            "evidence.json": [{"evidence_id": "ev_1", "period": period}],
            "citations.json": [{"evidence_id": "ev_1", "claim_ids": ["cl_1"], "used_in_report": True}],
            "verification_report.json": {"passed": True},
            "chart_consistency.json": {"passed": True},
            "search_meta.json": {"engine_meta": {}},
        }
        for name, payload in artifacts.items():
            self.outputs.joinpath(name).write_text(json.dumps(payload), encoding="utf-8")
        return {"report_md": str(self.reports / "report.md")}


def _write_quality_pipeline_artifacts(output_root, report_root, **_kwargs):
    payload = {
        "total_score": 0.9,
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
    }
    Path(output_root).joinpath("quality_report.json").write_text(json.dumps(payload), encoding="utf-8")
    return {"quality_report": {"total_score": 0.9, "objective_pass": True}}
