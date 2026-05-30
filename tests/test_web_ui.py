from datetime import date
import json
import os
from pathlib import Path
import threading
from urllib import error, request

from src.app.web_ui import (
    _confirmation_prompt,
    _create_run_dirs,
    _finalize_run_dirs,
    _latest_run_dirs,
    _is_confirmation_message,
    _report_artifact_url,
    _run_owner_routed_delivery_rework,
    _should_reset_engines_for_parsed_task,
    default_engines_for_symbol,
    load_run_payload,
    render_index_html,
    run_delivery_rework_loop,
    run_ui_server,
    sanitize_payload_for_user,
    validate_period_for_report,
)
from src.agents.base_agent import AgentStatus, TaskResult


def test_confirmation_message_accepts_real_chinese_yes_words():
    assert _is_confirmation_message("\u662f")
    assert _is_confirmation_message("\u786e\u8ba4")
    assert _is_confirmation_message("\u597d\u7684")
    assert _is_confirmation_message("ok")


def test_load_run_payload_reads_latest_artifacts(tmp_path):
    output_root = tmp_path / "outputs"
    report_root = tmp_path / "reports"
    output_root.mkdir()
    report_root.mkdir()
    (output_root / "run_summary.json").write_text('{"agent_count":6}', encoding="utf-8")
    (output_root / "charts.json").write_text('[{"chart_id":"c1"}]', encoding="utf-8")
    (output_root / "citations.json").write_text('[{"evidence_id":"ev1"}]', encoding="utf-8")
    (output_root / "tables.json").write_text('[{"statement":"income_statement"}]', encoding="utf-8")
    (output_root / "pdf_sections.json").write_text('[{"section_id":"pdf1"}]', encoding="utf-8")
    (output_root / "company_profile_extracted.json").write_text('{"has_profile_hints":true}', encoding="utf-8")
    (output_root / "quality_report.json").write_text('{"objective_pass":true}', encoding="utf-8")
    (output_root / "llm_quality_review.json").write_text('{"llm_review_pass":false}', encoding="utf-8")
    (output_root / "delivery_gate.json").write_text('{"delivery_pass":false}', encoding="utf-8")
    (output_root / "quality_remediation_plan.json").write_text('{"quality_feedback_used":true}', encoding="utf-8")
    (output_root / "agent_collaboration_trace.json").write_text('{"step_count":1}', encoding="utf-8")
    (output_root / "tool_trace.json").write_text('{"tool_call_count":2}', encoding="utf-8")
    (output_root / "delivery_rework_history.json").write_text('[{"round":1}]', encoding="utf-8")
    (output_root / "task_trace.jsonl").write_text(json.dumps({"agent": "PlanningAgent"}) + "\n", encoding="utf-8")
    (report_root / "report.md").write_text("# Report", encoding="utf-8")
    (report_root / "report.html").write_text("<html></html>", encoding="utf-8")

    payload = load_run_payload(output_root=output_root, report_root=report_root)

    assert payload["summary"]["agent_count"] == 6
    assert payload["charts"][0]["chart_id"] == "c1"
    assert payload["citations"][0]["evidence_id"] == "ev1"
    assert payload["tables"][0]["statement"] == "income_statement"
    assert payload["pdf_sections"][0]["section_id"] == "pdf1"
    assert payload["company_profile_extracted"]["has_profile_hints"] is True
    assert payload["quality_report"]["objective_pass"] is True
    assert payload["llm_quality_review"]["llm_review_pass"] is False
    assert payload["delivery_gate"]["delivery_pass"] is False
    assert payload["quality_remediation_plan"]["quality_feedback_used"] is True
    assert payload["agent_collaboration_trace"]["step_count"] == 1
    assert payload["tool_trace"]["tool_call_count"] == 2
    assert payload["delivery_rework_history"][0]["round"] == 1
    assert payload["trace"][0]["agent"] == "PlanningAgent"
    assert payload["report_html_url"].startswith("/artifacts/report.html?v=")
    assert payload["report_artifact_version"] != "0"


def test_report_artifact_url_uses_run_specific_path(monkeypatch, tmp_path):
    import src.app.web_ui as web_ui

    report_root = tmp_path / "reports"
    report_path = report_root / "runs" / "20260522_amd" / "reports"
    report_path.mkdir(parents=True)
    monkeypatch.setattr(web_ui, "DEFAULT_REPORT_DIR", report_root)

    url = _report_artifact_url(report_path, "report.html", "123")

    assert url == "/artifacts/runs/20260522_amd/reports/report.html?v=123"


def test_run_id_directories_are_isolated_and_latest_points_to_new_run(tmp_path):
    output_root = tmp_path / "outputs"
    report_root = tmp_path / "reports"
    first = _create_run_dirs(output_root, report_root, "NVDA", "2026Q1", "collaborative")
    second = _create_run_dirs(output_root, report_root, "TSLA", "2026Q1", "collaborative")
    (first["output_dir"] / "run_summary.json").write_text('{"symbol":"NVDA"}', encoding="utf-8")
    (first["report_dir"] / "report.md").write_text("# NVDA", encoding="utf-8")
    (second["output_dir"] / "run_summary.json").write_text('{"symbol":"TSLA"}', encoding="utf-8")
    (second["report_dir"] / "report.md").write_text("# TSLA", encoding="utf-8")

    _finalize_run_dirs(first, output_root, report_root, "NVDA", "2026Q1", "collaborative", {"delivery_gate": {"delivery_pass": False}})
    _finalize_run_dirs(second, output_root, report_root, "TSLA", "2026Q1", "collaborative", {"delivery_gate": {"delivery_pass": True}})
    latest = _latest_run_dirs(output_root, report_root)

    assert first["output_dir"].exists()
    assert second["output_dir"].exists()
    assert latest["output_dir"] == second["output_dir"]
    assert (report_root / "report.md").read_text(encoding="utf-8") == "# TSLA"
    assert (first["report_dir"] / "report.md").read_text(encoding="utf-8") == "# NVDA"


def test_latest_run_dirs_prefers_newer_run_when_latest_pointer_is_stale(tmp_path):
    output_root = tmp_path / "outputs"
    report_root = tmp_path / "reports"
    first = _create_run_dirs(output_root, report_root, "AAPL", "2026Q1", "collaborative")
    second = _create_run_dirs(output_root, report_root, "AMD", "2026Q1", "collaborative")
    first["output_dir"].mkdir(parents=True, exist_ok=True)
    first["report_dir"].mkdir(parents=True, exist_ok=True)
    second["output_dir"].mkdir(parents=True, exist_ok=True)
    second["report_dir"].mkdir(parents=True, exist_ok=True)
    (first["output_dir"] / "run_summary.json").write_text('{"symbol":"AAPL"}', encoding="utf-8")
    (second["output_dir"] / "run_summary.json").write_text('{"symbol":"AMD"}', encoding="utf-8")
    (first["report_dir"] / "report.md").write_text("# AAPL", encoding="utf-8")
    (second["report_dir"] / "report.md").write_text("# AMD", encoding="utf-8")
    stale = {"output_dir": str(first["output_dir"]), "report_dir": str(first["report_dir"])}
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "latest_run.json").write_text(json.dumps(stale), encoding="utf-8")
    old_time = 1_700_000_000
    new_time = old_time + 60
    for path in [first["output_dir"], first["report_dir"]]:
        os.utime(path, (old_time, old_time))
    for path in [second["output_dir"], second["report_dir"]]:
        os.utime(path, (new_time, new_time))

    latest = _latest_run_dirs(output_root, report_root)

    assert latest["output_dir"] == second["output_dir"]
    assert latest["report_dir"] == second["report_dir"]


def test_chat_api_general_dialogue_does_not_create_run_or_override_latest(tmp_path):
    output_root = tmp_path / "outputs"
    report_root = tmp_path / "reports"
    seed_run = _create_run_dirs(output_root, report_root, "AAPL", "2025Q4", "collaborative")
    (seed_run["output_dir"] / "run_summary.json").write_text(
        json.dumps({"symbol": "AAPL", "period": "2025Q4", "verification_passed": True}),
        encoding="utf-8",
    )
    (seed_run["report_dir"] / "report.md").write_text("# AAPL", encoding="utf-8")
    _finalize_run_dirs(
        seed_run,
        output_root,
        report_root,
        "AAPL",
        "2025Q4",
        "collaborative",
        {"delivery_gate": {"delivery_pass": True}},
    )
    run_count_before = len(list((output_root / "runs").iterdir()))

    config = _write_model_config(tmp_path)
    server, url = run_ui_server(
        port=0,
        output_dir=str(output_root),
        report_dir=str(report_root),
        config_path=str(config),
        memory_root=str(tmp_path / "memory"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = json.dumps(
            {
                "message": "你好，今天市场有什么值得关注？",
                "memory_enabled": True,
                "allow_report_run": True,
                "enable_remote_data": True,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        req = request.Request(
            f"{url}/api/chat",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with request.urlopen(req, timeout=5) as resp:
            chat_body = json.loads(resp.read().decode("utf-8"))

        with request.urlopen(f"{url}/api/latest", timeout=5) as resp:
            latest_body = json.loads(resp.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    run_count_after = len(list((output_root / "runs").iterdir()))
    assert chat_body["mode"] == "general_chat"
    assert run_count_after == run_count_before
    assert latest_body["summary"]["symbol"] == "AAPL"
    assert latest_body["summary"]["period"] == "2025Q4"


def test_chat_api_quality_review_reads_artifacts_without_new_run(tmp_path):
    output_root = tmp_path / "outputs"
    report_root = tmp_path / "reports"
    seed_run = _create_run_dirs(output_root, report_root, "AMD", "2025Q4", "collaborative")
    (seed_run["output_dir"] / "run_summary.json").write_text(
        json.dumps({"symbol": "AMD", "period": "2025Q4", "verification_passed": True}),
        encoding="utf-8",
    )
    (seed_run["output_dir"] / "quality_report.json").write_text(json.dumps({"total_score": 0.86}), encoding="utf-8")
    (seed_run["output_dir"] / "delivery_gate.json").write_text(
        json.dumps({"delivery_pass": False, "issues": [{"severity": "blocker", "message": "missing citation"}]}),
        encoding="utf-8",
    )
    (seed_run["output_dir"] / "verification_report.json").write_text(
        json.dumps({"passed": False, "evidence_gaps": [{"claim_id": "c1"}]}),
        encoding="utf-8",
    )
    (seed_run["output_dir"] / "claims.json").write_text(
        json.dumps([{"claim_id": "c1", "evidence_ids": []}]),
        encoding="utf-8",
    )
    (seed_run["output_dir"] / "citations.json").write_text(
        json.dumps([{"evidence_id": "ev1", "title": "source"}]),
        encoding="utf-8",
    )
    (seed_run["report_dir"] / "report.md").write_text("# AMD", encoding="utf-8")
    _finalize_run_dirs(
        seed_run,
        output_root,
        report_root,
        "AMD",
        "2025Q4",
        "collaborative",
        {"delivery_gate": {"delivery_pass": False}},
    )
    run_count_before = len(list((output_root / "runs").iterdir()))

    config = _write_model_config(tmp_path)
    server, url = run_ui_server(
        port=0,
        output_dir=str(output_root),
        report_dir=str(report_root),
        config_path=str(config),
        memory_root=str(tmp_path / "memory"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = json.dumps(
            {
                "message": "检查最近报告质量问题和引用缺口",
                "memory_enabled": True,
                "allow_report_run": True,
                "enable_remote_data": True,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        req = request.Request(
            f"{url}/api/chat",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    run_count_after = len(list((output_root / "runs").iterdir()))
    assert body["mode"] == "quality_review"
    assert run_count_after == run_count_before
    assert body["result"]["delivery_gate"]["delivery_pass"] is False
    assert "blocker" in body["answer"] or "阻塞" in body["answer"]


def test_chat_engine_reset_treats_hk_defaults_as_auto_selected():
    assert _should_reset_engines_for_parsed_task(True, "local_real_data,yahoo_finance,tavily,local_evidence") is True
    assert _should_reset_engines_for_parsed_task(False, "local_real_data,yahoo_finance,tavily,local_evidence") is False
    assert _should_reset_engines_for_parsed_task(True, "custom_engine") is False


def test_owner_routed_rework_backfills_data_before_claim_rebuild(tmp_path):
    output_root = tmp_path / "outputs"
    report_root = tmp_path / "reports"
    output_root.mkdir()
    report_root.mkdir()
    (output_root / "run_summary.json").write_text('{"symbol":"TSLA","period":"2026Q1"}', encoding="utf-8")
    (output_root / "evidence.json").write_text("[]", encoding="utf-8")
    (output_root / "claims.json").write_text("[]", encoding="utf-8")
    (output_root / "analysis_artifacts.json").write_text("{}", encoding="utf-8")
    (report_root / "report.md").write_text("# Old", encoding="utf-8")

    class FakeOrchestrator:
        def __init__(self):
            self.trace = []
            self.task_types = []

        def _execute(self, agent_key, task):
            self.task_types.append(task.task_type)
            self.trace.append({"agent_key": agent_key, "task_type": task.task_type})
            if task.task_type == "deep_researcher":
                return TaskResult(
                    task.task_id,
                    "DeepResearcherAgent",
                    AgentStatus.COMPLETED,
                    output={
                        "evidence_candidates": [{"evidence_id": "sec_ev", "source_type": "sec_filing", "symbol": "TSLA"}],
                        "search_meta": {"engine_meta": {"sec_edgar": {"record_count": 1}}},
                    },
                )
            if task.task_type == "browser":
                return TaskResult(
                    task.task_id,
                    "BrowserAgent",
                    AgentStatus.COMPLETED,
                    output={
                        "evidence_records": [
                            {
                                "evidence_id": "sec_ev",
                                "source_type": "sec_filing",
                                "symbol": "TSLA",
                                "period": "2026Q1",
                                "content": "filing",
                            }
                        ]
                    },
                )
            if task.task_type == "deep_analyze":
                return TaskResult(
                    task.task_id,
                    "DeepAnalyzeAgent",
                    AgentStatus.COMPLETED,
                    output={
                        "claims": [],
                        "analysis_artifacts": {
                            "financial_metrics": {"metric_count": 0},
                            "tables": [{"table_id": "tbl_income", "table_type": "income_statement"}],
                            "pdf_sections": [{"section_id": "pdf_1"}],
                        },
                    },
                    metadata={"evidence_gate": {"rejected_claim_count": 0}},
                )
            if task.task_type == "three_statement_analysis":
                return TaskResult(task.task_id, "StatementAgent", AgentStatus.COMPLETED, output={"role_outputs": {}})
            if task.task_type == "pre_write_critic":
                return TaskResult(task.task_id, "CriticAgent", AgentStatus.COMPLETED, output={"pre_write_critic": {}})
            if task.task_type == "final_answer":
                return TaskResult(
                    task.task_id,
                    "FinalAnswerAgent",
                    AgentStatus.COMPLETED,
                    output={"markdown": "# New", "html": "<h1>New</h1>", "report_json": {}},
                )
            raise AssertionError(task.task_type)

    remediation = {
        "responsible_agents": [
            {"agent": "DeepResearcherAgent"},
            {"agent": "BrowserAgent"},
            {"agent": "DeepAnalyzeAgent"},
            {"agent": "StatementAgent"},
        ],
        "required_fixes": ["backfill statements"],
    }
    result = _run_owner_routed_delivery_rework(
        orchestrator=FakeOrchestrator(),
        output_path=output_root,
        report_path=report_root,
        remediation=remediation,
        run_kwargs={"symbol": "TSLA", "period": "2026Q1", "search_engines": ["sec_edgar"], "enable_remote_data": True},
        round_index=1,
    )

    assert result["handled"] is True
    assert result["claim_rebuild_attempted"] is True
    assert result["target_agents_rerun"][0]["agent"] == "DeepResearcherAgent"
    assert json.loads((output_root / "search_meta.json").read_text(encoding="utf-8"))["engine_meta"]["sec_edgar"]["record_count"] == 1
    assert json.loads((output_root / "tables.json").read_text(encoding="utf-8"))[0]["table_type"] == "income_statement"
    assert json.loads((output_root / "pdf_sections.json").read_text(encoding="utf-8"))[0]["section_id"] == "pdf_1"


def test_delivery_rework_loop_reruns_when_gate_fails(tmp_path, monkeypatch):
    output_root = tmp_path / "outputs"
    report_root = tmp_path / "reports"
    output_root.mkdir()
    report_root.mkdir()
    (output_root / "quality_remediation_plan.json").write_text(
        '{"quality_feedback_used":true,"required_fixes":["fix tables"]}',
        encoding="utf-8",
    )

    class FakeOrchestrator:
        def __init__(self):
            self.calls = 0

        def run(self, **kwargs):
            self.calls += 1
            assert kwargs["quality_remediation_plan"]["quality_feedback_used"] is True
            return {}

    qualities = [
        {"delivery_gate": {"delivery_pass": True}, "top_quality_issues": []},
    ]

    def fake_quality(*args, **kwargs):
        return qualities.pop(0)

    monkeypatch.setattr("src.app.web_ui.run_delivery_quality_pipeline", fake_quality)
    orchestrator = FakeOrchestrator()
    result = run_delivery_rework_loop(
        orchestrator=orchestrator,
        output_path=output_root,
        report_path=report_root,
        config_path="config.yaml",
        initial_quality_result={"delivery_gate": {"delivery_pass": False}, "top_quality_issues": ["missing tables"]},
        run_kwargs={"research_topic": "x", "symbol": "AAPL", "period": "2025Q4"},
    )

    assert orchestrator.calls == 1
    assert result["reworked"] is True
    assert result["quality_result"]["delivery_gate"]["delivery_pass"] is True
    history = json.loads((output_root / "delivery_rework_history.json").read_text(encoding="utf-8"))
    assert history[0]["delivery_pass_after_round"] is True


def test_delivery_rework_loop_prefers_owner_routed_repair(tmp_path, monkeypatch):
    output_root = tmp_path / "outputs"
    report_root = tmp_path / "reports"
    output_root.mkdir()
    report_root.mkdir()
    (output_root / "quality_remediation_plan.json").write_text(
        json.dumps(
            {
                "quality_feedback_used": True,
                "responsible_agents": [{"agent": "StatementAgent"}, {"agent": "FinalAnswerAgent"}],
                "required_fixes": ["repair statements"],
            }
        ),
        encoding="utf-8",
    )

    class FakeOrchestrator:
        def run(self, **kwargs):
            raise AssertionError("owner-routed repair should avoid full pipeline rerun")

    def fake_owner_rework(**kwargs):
        return {
            "handled": True,
            "target_agents": ["StatementAgent", "FinalAnswerAgent"],
            "target_agents_rerun": [{"agent": "StatementAgent", "task_type": "three_statement_analysis"}],
            "critic_rechecked": True,
            "final_editor_rerun": True,
            "llm_repair_attempted": True,
            "unfixable_reasons": [],
        }

    monkeypatch.setattr("src.app.web_ui._run_owner_routed_delivery_rework", fake_owner_rework)
    monkeypatch.setattr(
        "src.app.web_ui.run_delivery_quality_pipeline",
        lambda *args, **kwargs: {"delivery_gate": {"delivery_pass": True}, "top_quality_issues": []},
    )

    result = run_delivery_rework_loop(
        orchestrator=FakeOrchestrator(),
        output_path=output_root,
        report_path=report_root,
        config_path="config.yaml",
        initial_quality_result={"delivery_gate": {"delivery_pass": False}, "top_quality_issues": ["missing statements"]},
        run_kwargs={"research_topic": "x", "symbol": "AAPL", "period": "2025Q4"},
    )

    assert result["reworked"] is True
    history = json.loads((output_root / "delivery_rework_history.json").read_text(encoding="utf-8"))
    assert history[0]["rework_mode"] == "owner_routed"
    assert history[0]["status"] == "completed"
    assert history[0]["target_agents"] == ["StatementAgent", "FinalAnswerAgent"]
    assert history[0]["final_editor_rerun"] is True


def test_delivery_rework_loop_escalates_data_failures_after_owner_repair(tmp_path, monkeypatch):
    output_root = tmp_path / "outputs"
    report_root = tmp_path / "reports"
    output_root.mkdir()
    report_root.mkdir()
    (output_root / "quality_remediation_plan.json").write_text(
        json.dumps(
            {
                "quality_feedback_used": True,
                "responsible_agents": [{"agent": "StatementAgent"}, {"agent": "FinalAnswerAgent"}],
                "required_fixes": ["repair three statement extraction"],
                "issues": [{"severity": "blocker", "message": "missing cash flow statement"}],
            }
        ),
        encoding="utf-8",
    )

    class FakeOrchestrator:
        def __init__(self):
            self.run_count = 0

        def run(self, **kwargs):
            self.run_count += 1
            return {"ok": True}

    fake_orchestrator = FakeOrchestrator()

    monkeypatch.setattr(
        "src.app.web_ui._run_owner_routed_delivery_rework",
        lambda **kwargs: {
            "handled": True,
            "target_agents": ["StatementAgent", "FinalAnswerAgent"],
            "target_agents_rerun": [{"agent": "StatementAgent", "task_type": "three_statement_analysis"}],
            "final_editor_rerun": True,
            "unfixable_reasons": [],
        },
    )
    quality_calls = [
        {"delivery_gate": {"delivery_pass": False, "issues": [{"severity": "blocker", "message": "missing cash flow statement"}]}, "top_quality_issues": []},
        {"delivery_gate": {"delivery_pass": True}, "top_quality_issues": []},
    ]
    monkeypatch.setattr("src.app.web_ui.run_delivery_quality_pipeline", lambda *args, **kwargs: quality_calls.pop(0))

    result = run_delivery_rework_loop(
        orchestrator=fake_orchestrator,
        output_path=output_root,
        report_path=report_root,
        config_path="configs/model_backends.yaml",
        initial_quality_result={"delivery_gate": {"delivery_pass": False}},
        run_kwargs={"research_topic": "x", "symbol": "NVDA", "period": "2026Q1"},
    )

    assert fake_orchestrator.run_count == 1
    assert result["quality_result"]["delivery_gate"]["delivery_pass"] is True
    history = json.loads((output_root / "delivery_rework_history.json").read_text(encoding="utf-8"))
    assert history[0]["rework_mode"] == "owner_routed_plus_full_pipeline_rerun"
    assert history[0]["escalated_full_pipeline_rerun"] is True


def test_delivery_rework_loop_records_skipped_when_orchestrator_missing(tmp_path):
    output_root = tmp_path / "outputs"
    report_root = tmp_path / "reports"
    output_root.mkdir()
    report_root.mkdir()

    result = run_delivery_rework_loop(
        orchestrator=None,
        output_path=output_root,
        report_path=report_root,
        config_path="config.yaml",
        initial_quality_result={"delivery_gate": {"delivery_pass": False}, "top_quality_issues": ["missing statements"]},
        run_kwargs={"research_topic": "x", "symbol": "NVDA", "period": "2026Q1"},
    )

    history = json.loads((output_root / "delivery_rework_history.json").read_text(encoding="utf-8"))
    assert result["reworked"] is False
    assert history[0]["status"] == "skipped"
    assert history[0]["handled"] is False
    assert "orchestrator unavailable" in history[0]["unfixable_reasons"][0]


def test_render_index_html_contains_chat_first_controls():
    html = render_index_html()

    assert "你今天想研究什么？" in html
    assert "直接问，例如：生成特斯拉最新财报研报" in html
    # User mode must NOT show developer debug panels or internal parameters
    assert "开发者诊断" not in html
    assert "数据源健康" not in html
    assert "多智能体协作" not in html
    assert "工具调用" not in html
    assert "async_report_run: true" not in html
    assert "backgroundRunPending" not in html
    # User mode must have confirmation card rendering
    assert "renderConfirmCard" in html
    assert "confirmAndRun" in html
    assert "modifyRequest" in html
    assert "currentRunRequest" in html

    # Developer mode includes debug panels
    dev_html = render_index_html(mode="developer")
    assert "开发者诊断" in dev_html
    assert "数据源健康" in dev_html
    assert "多智能体协作" in dev_html
    assert "工具调用" in dev_html
    assert "async_report_run: true" in dev_html
    assert "backgroundRunPending" in dev_html


def test_period_guard_blocks_unfinished_quarter_and_suggests_prior_period():
    guard = validate_period_for_report("2026Q2", today=date(2026, 5, 16))

    assert guard["ok"] is False
    assert "2026Q2 尚未结束" in guard["message"]
    assert "2026Q1" in guard["suggested_periods"]
    assert "2025Q4" in guard["suggested_periods"]


def test_chat_api_returns_friendly_period_guard_for_future_report(tmp_path):
    config = _write_model_config(tmp_path)
    server, url = run_ui_server(
        port=0,
        output_dir=str(tmp_path / "outputs"),
        report_dir=str(tmp_path / "reports"),
        config_path=str(config),
        memory_root=str(tmp_path / "memory"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = json.dumps(
            {
                "message": "生成 TSLA 2026Q4 公司财报研报",
                "memory_enabled": True,
                "allow_report_run": True,
                "enable_remote_data": True,
            }
        ).encode("utf-8")
        req = request.Request(
            f"{url}/api/chat",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert body["mode"] == "period_guard"
    assert body["period_guard"]["ok"] is False
    assert "2026Q4 尚未结束" in body["answer"]


def test_chat_api_period_guard_handles_chinese_future_quarter(tmp_path):
    config = _write_model_config(tmp_path)
    server, url = run_ui_server(
        port=0,
        output_dir=str(tmp_path / "outputs"),
        report_dir=str(tmp_path / "reports"),
        config_path=str(config),
        memory_root=str(tmp_path / "memory"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = json.dumps(
            {
                "message": "生成特斯拉26年第四季度财报研报",
                "memory_enabled": True,
                "allow_report_run": True,
                "enable_remote_data": True,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        req = request.Request(
            f"{url}/api/chat",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert body["mode"] == "period_guard"
    assert body["parsed_task"]["symbol"] == "TSLA"
    assert body["parsed_task"]["period"] == "2026Q4"
    assert "2026Q4 尚未结束" in body["answer"]


def test_default_realtime_engines_switch_by_symbol_market():
    assert "cninfo_announcements" in default_engines_for_symbol("600519.SS", realtime=True)
    assert "eastmoney_financials" in default_engines_for_symbol("600519", realtime=True)
    assert "sec_edgar" in default_engines_for_symbol("AMD", realtime=True)
    assert default_engines_for_symbol("AMD", realtime=False) == "local_real_data,yahoo_finance,tavily,local_evidence"


def test_chat_parsed_a_share_resets_stale_hk_engines(monkeypatch, tmp_path):
    captured = {}

    class FakeOrchestrator:
        def __init__(self, output_dir, report_dir, **kwargs):
            self.output_dir = Path(output_dir)
            self.report_dir = Path(report_dir)
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self.report_dir.mkdir(parents=True, exist_ok=True)

        def run(self, **kwargs):
            captured.update(kwargs)
            (self.output_dir / "citations.json").write_text("[]", encoding="utf-8")
            (self.output_dir / "run_summary.json").write_text(
                json.dumps({"verification_passed": True, "symbol": kwargs["symbol"], "period": kwargs["period"]}),
                encoding="utf-8",
            )
            (self.output_dir / "verification_report.json").write_text('{"passed": true}', encoding="utf-8")
            (self.output_dir / "task_trace.jsonl").write_text('{"agent":"fake","status":"completed"}\n', encoding="utf-8")
            (self.report_dir / "report.md").write_text("# Fake report", encoding="utf-8")
            return {"verification_passed": True}

    def fake_quality(*args, **kwargs):
        return {
            "quality_report": {"objective_pass": True},
            "llm_quality_review": {"llm_review_pass": True},
            "delivery_gate": {"delivery_pass": True},
        }

    monkeypatch.setattr("src.app.web_ui.MultiAgentOrchestrator", FakeOrchestrator)
    monkeypatch.setattr("src.app.web_ui.run_delivery_quality_pipeline", fake_quality)
    config = _write_model_config(tmp_path)
    server, url = run_ui_server(
        port=0,
        output_dir=str(tmp_path / "outputs"),
        report_dir=str(tmp_path / "reports"),
        config_path=str(config),
        memory_root=str(tmp_path / "memory"),
        mode="developer",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = json.dumps(
            {
                "message": "生成贵州茅台 2025Q4 公司研报",
                "engines": "local_real_data,hkex_announcements,yahoo_finance,tavily,serper,local_evidence",
                "memory_enabled": False,
                "allow_report_run": True,
                "enable_remote_data": True,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        req = request.Request(
            f"{url}/api/chat",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert body["parsed_task"]["symbol"] == "600519.SS"
    assert "cninfo_announcements" in captured["search_engines"]
    assert "exchange_announcements" in captured["search_engines"]
    assert "hkex_announcements" not in captured["search_engines"]


def test_run_api_rejects_unfinished_period(tmp_path):
    config = _write_model_config(tmp_path)
    server, url = run_ui_server(
        port=0,
        output_dir=str(tmp_path / "outputs"),
        report_dir=str(tmp_path / "reports"),
        config_path=str(config),
        memory_root=str(tmp_path / "memory"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = json.dumps({"symbol": "600519.SS", "period": "2099Q4"}).encode("utf-8")
        req = request.Request(
            f"{url}/api/run",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        status_code = 0
        try:
            request.urlopen(req, timeout=3)
            assert False, "expected HTTP 400"
        except error.HTTPError as exc:
            status_code = exc.code
            body = json.loads(exc.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert status_code == 400
    assert body["period_guard"]["ok"] is False


def test_chat_api_returns_fallback_response_without_key(tmp_path):
    config = _write_model_config(tmp_path)
    server, url = run_ui_server(
        port=0,
        output_dir=str(tmp_path / "outputs"),
        report_dir=str(tmp_path / "reports"),
        config_path=str(config),
        memory_root=str(tmp_path / "memory"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = json.dumps({"message": "我喜欢简洁回答", "memory_enabled": True}).encode("utf-8")
        req = request.Request(
            f"{url}/api/chat",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with request.urlopen(req, timeout=3) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert body["answer"]
    assert body["mode"] == "general_chat"
    assert body["memory_used"]["enabled"] is True


def test_chat_api_parses_formal_company_name_and_fiscal_year_without_running(tmp_path):
    config = _write_model_config(tmp_path)
    server, url = run_ui_server(
        port=0,
        output_dir=str(tmp_path / "outputs"),
        report_dir=str(tmp_path / "reports"),
        config_path=str(config),
        memory_root=str(tmp_path / "memory"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = json.dumps(
            {
                "message": "\u8bf7\u751f\u6210\u817e\u8baf\u63a7\u80a1 FY2024 \u516c\u53f8\u7814\u62a5",
                "memory_enabled": False,
                "allow_report_run": False,
                "enable_remote_data": False,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        req = request.Request(
            f"{url}/api/chat",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert body["parsed_task"]["symbol"] == "0700.HK"
    assert body["parsed_task"]["period"] == "FY2024"
    assert body["parsed_task"]["period_kind"] == "fiscal_year"
    assert body["parsed_task"]["should_run"] is True


def test_chat_api_routes_report_run_and_returns_trace(monkeypatch, tmp_path):
    captured = {}

    class FakeOrchestrator:
        def __init__(self, output_dir, report_dir, **kwargs):
            self.output_dir = tmp_path / "outputs"
            self.report_dir = tmp_path / "reports"
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self.report_dir.mkdir(parents=True, exist_ok=True)

        def run(self, **kwargs):
            captured.update(kwargs)
            (self.output_dir / "citations.json").write_text("[]", encoding="utf-8")
            (self.output_dir / "run_summary.json").write_text(
                json.dumps(
                    {
                        "verification_passed": True,
                        "symbol": kwargs["symbol"],
                        "period": kwargs["period"],
                        "search_engines": kwargs["search_engines"],
                    }
                ),
                encoding="utf-8",
            )
            (self.output_dir / "verification_report.json").write_text('{"passed": true}', encoding="utf-8")
            (self.output_dir / "task_trace.jsonl").write_text('{"agent":"fake","status":"completed"}\n', encoding="utf-8")
            (self.report_dir / "report.md").write_text("# Fake report", encoding="utf-8")
            return {"verification_passed": True, "report_md": str(self.report_dir / "report.md")}

    def fake_quality(*args, **kwargs):
        return {
            "quality_report": {"objective_pass": True},
            "llm_quality_review": {"llm_review_pass": True},
            "delivery_gate": {"delivery_pass": True},
            "top_quality_issues": [],
        }

    monkeypatch.setattr("src.app.web_ui.MultiAgentOrchestrator", FakeOrchestrator)
    monkeypatch.setattr("src.app.web_ui.run_delivery_quality_pipeline", fake_quality)
    config = _write_model_config(tmp_path)
    server, url = run_ui_server(
        port=0,
        output_dir=str(tmp_path / "outputs"),
        report_dir=str(tmp_path / "reports"),
        config_path=str(config),
        memory_root=str(tmp_path / "memory"),
        mode="developer",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = json.dumps(
            {
                "message": "请生成贵州茅台 2025Q4 公司研报",
                "memory_enabled": True,
                "allow_report_run": True,
                "enable_remote_data": True,
            }
        ).encode("utf-8")
        req = request.Request(
            f"{url}/api/chat",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert body["mode"] == "report_generation_completed"
    assert body["result"]["verification_passed"] is True
    assert body["result"]["delivery_gate"]["delivery_pass"] is True
    assert body["parsed_task"]["symbol"] == "600519.SS"
    assert body["parsed_task"]["period"] == "2025Q4"
    assert captured["enable_remote_data"] is True
    assert captured["symbol"] == "600519.SS"
    assert captured["period"] == "2025Q4"
    assert "cninfo_announcements" in captured["search_engines"]
    assert body["latest"]["summary"]["symbol"] == "600519.SS"


def test_chat_api_asks_confirmation_for_underspecified_report(monkeypatch, tmp_path):
    class FakeOrchestrator:
        def __init__(self, **kwargs):
            raise AssertionError("orchestrator should not run without confirmed report params")

    monkeypatch.setattr("src.app.web_ui.MultiAgentOrchestrator", FakeOrchestrator)
    # Patch intent_classify to return "report_generation" — the fallback
    # with empty API key classifies "AMD 研报怎么看" as data_query (has question mark).
    monkeypatch.setattr(
        "src.app.web_ui.QueryUnderstanding.intent_classify",
        lambda self, msg: "report_generation",
    )
    config = _write_model_config(tmp_path)
    server, url = run_ui_server(
        port=0,
        output_dir=str(tmp_path / "outputs"),
        report_dir=str(tmp_path / "reports"),
        config_path=str(config),
        memory_root=str(tmp_path / "memory"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = json.dumps(
            {
                "message": "AMD 研报怎么看",
                "memory_enabled": True,
                "allow_report_run": True,
                "enable_remote_data": True,
            }
        ).encode("utf-8")
        req = request.Request(
            f"{url}/api/chat",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert body["mode"] == "confirm_report"
    assert body["parsed_task"]["symbol"] == "AMD"
    assert "请确认报告设置" in body["answer"]
    assert "local_real_data" not in body["answer"]
    assert "sec_edgar" not in body["answer"]
    assert "yahoo_finance" not in body["answer"]
    assert body.get("confirm_data") is not None
    assert "company_name" in body["confirm_data"]
    assert "AMD" in body["confirm_data"]["symbol"] or "AMD" == body["confirm_data"]["symbol"]


def test_chat_api_confirmed_pending_report_runs_original_task(monkeypatch, tmp_path):
    captured = {}

    class FakeOrchestrator:
        def __init__(self, output_dir, report_dir, **kwargs):
            self.output_dir = tmp_path / "outputs"
            self.report_dir = tmp_path / "reports"
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self.report_dir.mkdir(parents=True, exist_ok=True)

        def run(self, **kwargs):
            captured.update(kwargs)
            (self.output_dir / "citations.json").write_text("[]", encoding="utf-8")
            (self.output_dir / "run_summary.json").write_text(
                json.dumps(
                    {
                        "verification_passed": True,
                        "symbol": kwargs["symbol"],
                        "period": kwargs["period"],
                        "search_engines": kwargs["search_engines"],
                    }
                ),
                encoding="utf-8",
            )
            (self.output_dir / "verification_report.json").write_text('{"passed": true}', encoding="utf-8")
            (self.output_dir / "quality_report.json").write_text('{"objective_pass": true}', encoding="utf-8")
            (self.output_dir / "llm_quality_review.json").write_text('{"llm_review_pass": true}', encoding="utf-8")
            (self.output_dir / "delivery_gate.json").write_text('{"delivery_pass": true}', encoding="utf-8")
            (self.output_dir / "task_trace.jsonl").write_text('{"agent":"fake","status":"completed"}\n', encoding="utf-8")
            (self.report_dir / "report.md").write_text("# Apple report", encoding="utf-8")
            return {"verification_passed": True, "report_md": str(self.report_dir / "report.md")}

    def fake_quality(*args, **kwargs):
        return {
            "quality_report": {"objective_pass": True},
            "llm_quality_review": {"llm_review_pass": True},
            "delivery_gate": {"delivery_pass": True},
        }

    monkeypatch.setattr("src.app.web_ui.MultiAgentOrchestrator", FakeOrchestrator)
    monkeypatch.setattr("src.app.web_ui.run_delivery_quality_pipeline", fake_quality)
    # First message "苹果研报怎么看" → report_generation; second "是" → confirmation
    _call_count = [0]
    def _smart_intent(self, msg):
        _call_count[0] += 1
        if _call_count[0] >= 2:
            return "confirmation"
        return "report_generation"
    monkeypatch.setattr(
        "src.app.web_ui.QueryUnderstanding.intent_classify",
        _smart_intent,
    )
    config = _write_model_config(tmp_path)
    server, url = run_ui_server(
        port=0,
        output_dir=str(tmp_path / "outputs"),
        report_dir=str(tmp_path / "reports"),
        config_path=str(config),
        memory_root=str(tmp_path / "memory"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        first_payload = json.dumps(
            {
                "message": "\u82f9\u679c\u7814\u62a5\u600e\u4e48\u770b",
                "session_id": "apple-confirm",
                "symbol": "0700.HK",
                "period": "2026Q1",
                "memory_enabled": True,
                "allow_report_run": True,
                "enable_remote_data": True,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        first_req = request.Request(
            f"{url}/api/chat",
            data=first_payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with request.urlopen(first_req, timeout=5) as resp:
            first_body = json.loads(resp.read().decode("utf-8"))

        second_payload = json.dumps(
            {
                "message": "\u662f",
                "session_id": "apple-confirm",
                "symbol": "0700.HK",
                "period": "2026Q1",
                "memory_enabled": True,
                "allow_report_run": True,
                "enable_remote_data": True,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        second_req = request.Request(
            f"{url}/api/chat",
            data=second_payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with request.urlopen(second_req, timeout=5) as resp:
            second_body = json.loads(resp.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert first_body["mode"] == "confirm_report"
    assert first_body["parsed_task"]["symbol"] == "AAPL"
    assert second_body["mode"] == "report_generation_completed"
    assert second_body["parsed_task"]["symbol"] == "AAPL"
    assert second_body["parsed_task"]["period"] == "2026Q1"
    assert captured["symbol"] == "AAPL"
    assert captured["period"] == "2026Q1"
    assert "sec_edgar" in captured["search_engines"]
    assert second_body["latest"]["summary"]["symbol"] == "AAPL"


def test_confirmation_prompt_user_mode_hides_raw_engines():
    """User mode confirmation must NOT show raw engine names."""
    result = _confirmation_prompt("AMD", "2026Q1", ["local_real_data", "sec_edgar", "yahoo_finance"], mode="user")
    assert "local_real_data" not in result, "user mode must hide raw engine keys"
    assert "sec_edgar" not in result, "user mode must hide raw engine keys"
    assert "yahoo_finance" not in result, "user mode must hide raw engine keys"
    assert "请确认报告设置" in result, "user mode should show friendly title"
    assert "公司" in result, "user mode should mention the company"


def test_confirmation_prompt_user_mode_shows_human_readable_sources():
    """User mode confirmation must show human-readable data source descriptions."""
    result = _confirmation_prompt("TSLA", "2026Q1", ["local_real_data", "sec_edgar", "yahoo_finance"], mode="user")
    assert "local_real_data" not in result
    assert "sec_edgar" not in result
    assert "公司公开披露" in result or "SEC" in result, "user mode should describe sources in plain language"
    assert "local_evidence" not in result


def test_confirmation_prompt_developer_mode_shows_raw_engines():
    """Developer mode confirmation must show raw engine names."""
    result = _confirmation_prompt("AMD", "2026Q1", ["local_real_data", "sec_edgar", "yahoo_finance", "tavily"], mode="developer")
    assert "local_real_data" in result, "dev mode must show raw engine key"
    assert "sec_edgar" in result, "dev mode must show raw engine key"
    assert "yahoo_finance" in result, "dev mode must show raw engine key"
    assert "tavily" in result, "dev mode must show raw engine key"


def test_confirmation_prompt_developer_mode_contains_raw_keys():
    """Developer mode confirmation includes raw engines list."""
    result = _confirmation_prompt("AMD", "2026Q1", ["local_real_data", "sec_edgar"], mode="developer")
    assert "数据源：" in result
    assert "local_real_data" in result
    assert "sec_edgar" in result


def test_sanitize_payload_for_user_strips_debug_fields():
    """sanitize_payload_for_user must strip debug/quality data."""
    from src.app.web_ui import sanitize_payload_for_user
    raw = {
        "summary": {"symbol": "AMD", "period": "2026Q1"},
        "delivery_gate": {"delivery_pass": False},
        "quality_report": {"total_score": 0.5},
        "llm_quality_review": {"llm_review_pass": True},
        "tool_trace": [{"stage": "think"}],
        "report_links": {"html_web_url": "/artifacts/test"},
        "run_id": "test-run",
        "citations": [{"evidence_id": "ev1", "title": "source", "source_url": "http://example.com"}],
    }
    safe = sanitize_payload_for_user(raw)
    assert "summary" in safe
    assert "report_links" in safe
    assert "delivery_gate" not in safe
    assert "quality_report" not in safe
    assert "llm_quality_review" not in safe
    assert "tool_trace" not in safe


def test_human_readable_data_sources_maps_known_engines():
    """_human_readable_data_sources must map raw keys to friendly labels."""
    from src.app.web_ui import _human_readable_data_sources
    result = _human_readable_data_sources(["local_real_data", "sec_edgar", "yahoo_finance"])
    assert "local_real_data" not in result
    assert "sec_edgar" not in result
    assert "本地已缓存财务数据" in result
    assert "SEC 官方披露" in result
    assert "行情与市场数据" in result


def test_confirm_data_in_chat_api_has_required_fields(monkeypatch, tmp_path):
    """Confirm report response must include confirm_data with friendly fields."""
    class FakeOrchestrator:
        def __init__(self, **kwargs):
            raise AssertionError("orchestrator should not run")
    monkeypatch.setattr("src.app.web_ui.MultiAgentOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(
        "src.app.web_ui.QueryUnderstanding.intent_classify",
        lambda self, msg: "report_generation",
    )
    config = _write_model_config(tmp_path)
    server, url = run_ui_server(
        port=0,
        output_dir=str(tmp_path / "outputs"),
        report_dir=str(tmp_path / "reports"),
        config_path=str(config),
        memory_root=str(tmp_path / "memory"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = json.dumps({
            "message": "我想看 AMD 研报",
            "memory_enabled": False,
            "allow_report_run": True,
            "enable_remote_data": False,
        }).encode("utf-8")
        req = request.Request(
            f"{url}/api/chat",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert body["mode"] == "confirm_report"
    assert "confirm_data" in body
    cd = body["confirm_data"]
    assert "company_name" in cd
    assert "symbol" in cd and ("AMD" in cd["symbol"] or "NVDA" in cd["symbol"])
    assert "market" in cd
    assert "period" in cd
    assert "analysis_scope" in cd and len(cd["analysis_scope"]) >= 3
    assert "data_sources_hint" in cd


def _write_model_config(tmp_path):
    config = tmp_path / "model_backends.yaml"
    config.write_text(
        """
agent_model:
  provider: deepseek
  model_name: deepseek-test
  base_url: https://api.deepseek.com
  api_key: ""
  timeout: 1
  retry: 0
  max_tokens: 256
  temperature: 0.1
""".strip(),
        encoding="utf-8",
    )
    return config


def _seed_completed_run(output_root, report_root, symbol, period, run_id_suffix=""):
    """Helper: create a fake completed run with report.html for testing."""
    from src.app.web_ui import _create_run_dirs, _finalize_run_dirs

    run_paths = _create_run_dirs(output_root, report_root, symbol, period, "collaborative")
    (run_paths["output_dir"] / "run_summary.json").write_text(
        json.dumps({"symbol": symbol, "period": period, "run_id": run_paths["run_id"] + run_id_suffix,
                     "verification_passed": True}),
        encoding="utf-8",
    )
    (run_paths["report_dir"] / "report.html").write_text(
        f"<html><body><h1>{symbol} Report</h1></body></html>",
        encoding="utf-8",
    )
    (run_paths["report_dir"] / "report.md").write_text(f"# {symbol} Report", encoding="utf-8")
    _finalize_run_dirs(
        run_paths, output_root, report_root, symbol, period, "collaborative",
        {"delivery_gate": {"delivery_pass": True}},
    )
    return run_paths


def test_chat_api_report_artifact_request_returns_existing_report(monkeypatch, tmp_path):
    """'给我刚才生成的html' with existing report → returns report_artifact, not generation."""
    output_root = tmp_path / "outputs"
    report_root = tmp_path / "reports"
    _seed_completed_run(output_root, report_root, "TSLA", "2026Q1")

    monkeypatch.setattr(
        "src.app.web_ui.QueryUnderstanding.intent_classify",
        lambda self, msg: "report_artifact_request",
    )
    config = _write_model_config(tmp_path)
    server, url = run_ui_server(
        port=0,
        output_dir=str(output_root),
        report_dir=str(report_root),
        config_path=str(config),
        memory_root=str(tmp_path / "memory"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = json.dumps({
            "message": "给我刚才生成的html",
            "memory_enabled": False,
            "allow_report_run": True,
            "enable_remote_data": False,
        }).encode("utf-8")
        req = request.Request(f"{url}/api/chat", data=payload, method="POST",
                              headers={"Content-Type": "application/json"})
        with request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)

    assert body["mode"] == "report_artifact", f"expected report_artifact, got {body['mode']}"
    assert body.get("found") is not False, "should have found a report"
    assert "report_links" in body, "should include report_links"
    assert "html_web_url" in body["report_links"], "should include html_web_url"
    assert body["report_links"]["html_web_url"].startswith("/artifacts/"), \
        f"unexpected html_web_url: {body['report_links']['html_web_url']}"


def test_chat_api_report_artifact_request_does_not_consume_pending(monkeypatch, tmp_path):
    """pending_report_task exists but user asks for HTML → not consumed, returns artifact."""
    from src.app.web_ui import pending_report_tasks

    output_root = tmp_path / "outputs"
    report_root = tmp_path / "reports"
    _seed_completed_run(output_root, report_root, "TSLA", "2026Q1")

    # Seed a pending task
    pending_report_tasks["artifact-session"] = {"symbol": "AAPL", "period": "2026Q1", "research_topic": "test"}

    call_log = []
    def _artifact_aware_intent(self, msg):
        call_log.append(msg)
        return "report_artifact_request"

    monkeypatch.setattr(
        "src.app.web_ui.QueryUnderstanding.intent_classify",
        _artifact_aware_intent,
    )
    config = _write_model_config(tmp_path)
    server, url = run_ui_server(
        port=0,
        output_dir=str(output_root),
        report_dir=str(report_root),
        config_path=str(config),
        memory_root=str(tmp_path / "memory"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = json.dumps({
            "message": "给我 HTML",
            "session_id": "artifact-session",
            "memory_enabled": False,
            "allow_report_run": True,
            "enable_remote_data": False,
        }).encode("utf-8")
        req = request.Request(f"{url}/api/chat", data=payload, method="POST",
                              headers={"Content-Type": "application/json"})
        with request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)
        pending_report_tasks.pop("artifact-session", None)

    assert body["mode"] == "report_artifact", f"expected report_artifact, got {body['mode']}"
    # Pending task should not have been consumed
    assert "AAPL" not in body.get("symbol", "")


def test_chat_api_confirmation_consumes_pending_task(monkeypatch, tmp_path):
    """Only '是/确认' should consume pending task — not artifact requests."""
    import unittest.mock as _mock
    from src.app.web_ui import pending_report_tasks

    output_root = tmp_path / "outputs"
    report_root = tmp_path / "reports"

    config = _write_model_config(tmp_path)

    call_log = []
    def _confirm_intent(self, msg):
        call_log.append(msg)
        return "confirmation"

    monkeypatch.setattr(
        "src.app.web_ui.QueryUnderstanding.intent_classify",
        _confirm_intent,
    )
    monkeypatch.setattr("src.app.web_ui.MultiAgentOrchestrator", lambda *a, **kw: _mock.MagicMock())
    monkeypatch.setattr("src.app.web_ui.run_delivery_quality_pipeline", lambda *a, **kw: {
        "quality_report": {"objective_pass": True},
        "llm_quality_review": {"llm_review_pass": True},
        "delivery_gate": {"delivery_pass": True},
    })
    monkeypatch.setattr("src.app.web_ui.validate_period_for_report", lambda *a, **kw: {"ok": True})
    monkeypatch.setattr("src.app.web_ui._create_run_dirs", lambda *a, **kw: {
        "output_dir": tmp_path / "runs" / "tsla",
        "report_dir": tmp_path / "reports" / "tsla",
    })

    server, url = run_ui_server(
        port=0,
        output_dir=str(output_root),
        report_dir=str(report_root),
        config_path=str(config),
        memory_root=str(tmp_path / "memory"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # Must set pending task AFTER server start — create_ui_handler clears it
    pending_report_tasks["confirm-session"] = {"symbol": "TSLA", "period": "2026Q1", "research_topic": "test"}
    try:
        payload = json.dumps({
            "message": "是",
            "session_id": "confirm-session",
            "memory_enabled": False,
            "allow_report_run": True,
            "enable_remote_data": False,
            "async_report_run": True,
        }).encode("utf-8")
        req = request.Request(f"{url}/api/chat", data=payload, method="POST",
                              headers={"Content-Type": "application/json"})
        with request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)
        pending_report_tasks.pop("confirm-session", None)

    # With pending task + confirmation intent, should attempt generation (running or completed)
    assert body["mode"] in ("report_generation_running", "report_generation_completed"), \
        f"expected generation mode, got {body['mode']}"


def test_chat_api_artifact_not_found_shows_new_report_button(monkeypatch, tmp_path):
    """No existing report → report_artifact mode with found=False and helpful message."""
    output_root = tmp_path / "outputs"
    report_root = tmp_path / "reports"

    monkeypatch.setattr(
        "src.app.web_ui.QueryUnderstanding.intent_classify",
        lambda self, msg: "report_artifact_request",
    )
    config = _write_model_config(tmp_path)
    server, url = run_ui_server(
        port=0,
        output_dir=str(output_root),
        report_dir=str(report_root),
        config_path=str(config),
        memory_root=str(tmp_path / "memory"),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = json.dumps({
            "message": "给我之前生成的报告",
            "memory_enabled": False,
            "allow_report_run": True,
            "enable_remote_data": False,
        }).encode("utf-8")
        req = request.Request(f"{url}/api/chat", data=payload, method="POST",
                              headers={"Content-Type": "application/json"})
        with request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)

    assert body["mode"] == "report_artifact", f"expected report_artifact, got {body['mode']}"
    assert body.get("found") is False, "should indicate no report found"


def test_resolve_report_artifact_finds_by_symbol(monkeypatch, tmp_path):
    """resolve_report_artifact finds report by symbol match."""
    from src.app.web_ui import resolve_report_artifact

    output_root = tmp_path / "outputs"
    report_root = tmp_path / "reports"
    _seed_completed_run(output_root, report_root, "NVDA", "2026Q1")

    result = resolve_report_artifact(output_root=output_root, report_root=report_root, symbol="NVDA")
    assert result["found"] is True
    assert result["symbol"] == "NVDA"
    assert "report_links" in result
    assert result["report_links"].get("html_web_url", "").startswith("/artifacts/")


def test_resolve_report_artifact_not_found_returns_false(monkeypatch, tmp_path):
    """resolve_report_artifact with no runs at all returns found=False."""
    from src.app.web_ui import resolve_report_artifact

    output_root = tmp_path / "outputs"
    report_root = tmp_path / "reports"

    result = resolve_report_artifact(output_root=output_root, report_root=report_root, symbol="UNKNOWN")
    assert result["found"] is False
