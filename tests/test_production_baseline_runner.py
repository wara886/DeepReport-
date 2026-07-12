from scripts.run_production_baseline import build_summary, build_task_payload, render_markdown, summarize_case


def test_build_task_payload_uses_production_runtime_contract():
    payload = build_task_payload(task_id="baseline-aapl", symbol="AAPL", company_name="Apple Inc.", period="FY2024")

    assert payload["run_immediately"] is True
    assert payload["run_async"] is True
    assert payload["execution_tier"] == "delivery"
    assert payload["fast"] is False
    assert payload["enable_remote_data"] is True
    assert payload["enforce_evidence_gate"] is True


def test_summarize_case_reads_production_artifacts(tmp_path):
    (tmp_path / "delivery_gate.json").write_text(
        '{"delivery_pass":false,"scores":{"objective_total_score":0.82,"llm_total_score":0.7},'
        '"issues":[{"severity":"blocker","category":"evidence_consumption"}]}',
        encoding="utf-8",
    )
    (tmp_path / "run_summary.json").write_text(
        '{"total_duration_sec":12.5,"executed_agents":["research","analyze"]}', encoding="utf-8"
    )
    (tmp_path / "canonical_metrics.json").write_text('{"metrics":[{"metric_name":"revenue"}]}', encoding="utf-8")
    (tmp_path / "evidence.json").write_text('[{"evidence_id":"ev-1"}]', encoding="utf-8")
    (tmp_path / "search_meta.json").write_text(
        '{"engine_meta":{"local_evidence":{"retrieval_available":false,"failure_reason":"no_records"}}}',
        encoding="utf-8",
    )
    (tmp_path / "section_evidence_packs.json").write_text('{"packs":{"financial_analysis":{}}}', encoding="utf-8")
    task = {
        "task_id": "baseline-aapl",
        "symbol": "AAPL",
        "period": "FY2024",
        "status": "quality_failed",
        "quality_score": 0.82,
        "workspace_id": 1,
        "company_id": None,
        "metadata": {"output_dir": str(tmp_path)},
        "delivery_readiness": {"can_deliver_formal_report": False},
        "events": [{"stage": "orchestrator", "status": "success"}],
    }

    result = summarize_case(task, diagnostics={"root_causes": [{"code": "writer"}]})

    assert result["evidence_count"] == 1
    assert result["canonical_metric_count"] == 1
    assert result["section_pack_count"] == 1
    assert result["local_retrieval"]["failure_reason"] == "no_records"
    assert result["delivery_gate"]["blocker_categories"] == ["evidence_consumption"]


def test_summary_and_markdown_report_delivery_rate():
    cases = [
        {"formal_delivery": True, "quality_score": 0.9, "company_id": 1, "symbol": "AAPL", "status": "completed", "evidence_count": 1, "canonical_metric_count": 1, "local_retrieval": {}, "delivery_gate": {"blocker_count": 0}},
        {"formal_delivery": False, "quality_score": 0.7, "company_id": None, "symbol": "MSFT", "status": "quality_failed", "evidence_count": 1, "canonical_metric_count": 0, "local_retrieval": {"failure_reason": "no_records"}, "delivery_gate": {"blocker_count": 2}},
    ]

    summary = build_summary(cases=cases, base_url="http://test", period="FY2024", generated_at="now")
    markdown = render_markdown(summary)

    assert summary["summary"]["formal_delivery_rate"] == 0.5
    assert summary["summary"]["average_quality_score"] == 0.8
    assert summary["summary"]["unbound_company_count"] == 1
    assert "| MSFT | quality_failed |" in markdown
