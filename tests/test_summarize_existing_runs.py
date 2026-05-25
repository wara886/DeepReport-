import json
import os

from scripts.summarize_existing_runs import summarize_existing_runs


def test_summarizer_selects_latest_complete_run_and_reports_missing_cases(tmp_path):
    old_complete = _write_run(tmp_path / "runs" / "20260520_amd_2026q1_collaborative", complete=True)
    new_incomplete = _write_run(tmp_path / "runs" / "20260522_amd_2026q1_collaborative", complete=False)
    benchmark_output = _write_run(
        tmp_path / "eval_outputs" / "benchmark_quick9_multi_agent" / "runs" / "new_amd" / "company",
        complete=True,
    )
    os.utime(old_complete, (10, 10))
    os.utime(new_incomplete, (20, 20))
    os.utime(benchmark_output, (30, 30))
    config = tmp_path / "benchmark.yaml"
    config.write_text(
        f"""
benchmark:
  existing_run_roots:
    - {tmp_path.as_posix()}/**/outputs
  excluded_run_roots:
    - {tmp_path.as_posix()}/eval_outputs/benchmark_*/**/company/outputs
  cases:
    - case_id: amd
      market: US
      company_name: AMD
      canonical_symbol: AMD
      period_policy: latest_complete_existing_artifact
    - case_id: tsla
      market: US
      company_name: Tesla
      canonical_symbol: TSLA
      period_policy: latest_complete_existing_artifact
""".strip(),
        encoding="utf-8",
    )

    result = summarize_existing_runs(
        config_path=config,
        output_dir=tmp_path / "results",
        project_root=tmp_path,
    )

    assert result["observed_run_count"] == 1
    assert result["evaluable_run_count"] == 1
    assert result["not_run_count"] == 1
    amd = result["records"][0]
    assert amd["status"] == "evaluated"
    assert str(old_complete) in amd["outputs_dir"]
    assert str(new_incomplete) in amd["ignored_run_dirs"]
    assert str(benchmark_output) not in amd["ignored_run_dirs"]
    assert (tmp_path / "results" / "benchmark_summary.csv").exists()
    assert (tmp_path / "results" / "benchmark_failures.csv").exists()
    assert "not_run" in (tmp_path / "results" / "benchmark_failures.csv").read_text(encoding="utf-8")


def _write_run(root, complete):
    outputs = root / "outputs"
    reports = root / "reports"
    outputs.mkdir(parents=True)
    reports.mkdir(parents=True)
    (outputs / "run_summary.json").write_text(
        json.dumps({"symbol": "AMD", "period": "2026Q1", "entity_resolution": {"resolved_symbol": "AMD"}}),
        encoding="utf-8",
    )
    (reports / "report.md").write_text(
        "## 执行摘要\n完整。[ev_1]\n## 风险提示\n风险。\n## 投资结论\n基于估值维持中性。\n## 估值\nP/E 20x。\n",
        encoding="utf-8",
    )
    if complete:
        payloads = {
            "claims.json": [{"claim_id": "cl_1", "section_name": "risks", "evidence_ids": ["ev_1"]}],
            "evidence.json": [{"evidence_id": "ev_1"}],
            "citations.json": [{"evidence_id": "ev_1", "claim_ids": ["cl_1"], "used_in_report": True}],
            "verification_report.json": {"passed": True},
            "quality_report.json": {
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
            },
        }
        for name, payload in payloads.items():
            (outputs / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return outputs
