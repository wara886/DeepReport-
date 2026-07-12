import json

from src.services.report_task_service import _build_generation_execution_summary


def test_generation_execution_summary_attributes_agent_and_tool_failures(tmp_path):
    (tmp_path / "evidence.json").write_text("[]", encoding="utf-8")
    (tmp_path / "claims.json").write_text("[]", encoding="utf-8")
    (tmp_path / "run_summary.json").write_text(
        json.dumps(
            {
                "executed_agents": ["research", "final_answer"],
                "model_usage_by_agent": {"research": {"model_name": "deepseek"}},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "agent_collaboration_trace.json").write_text(
        json.dumps(
            {
                "agents": [
                    {"agent": "research", "task_type": "search", "status": "failed", "error": "source timeout"},
                    {"agent": "final_answer", "task_type": "writing", "status": "completed", "error": ""},
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "tool_trace.json").write_text(
        json.dumps(
            {
                "calls": [
                    {
                        "caller_agent": "research",
                        "tool_name": "hkex",
                        "success": False,
                        "failure_reason": "timeout",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    summary = _build_generation_execution_summary(tmp_path)

    assert summary["status"] == "failed"
    assert summary["root_cause"] == "agent_execution_failed"
    assert summary["failed_agents"] == [
        {"agent": "research", "task_type": "search", "status": "failed", "error": "source timeout"}
    ]
    assert summary["failed_tools"][0]["tool_name"] == "hkex"


def test_generation_execution_summary_distinguishes_missing_trace(tmp_path):
    (tmp_path / "evidence.json").write_text("[]", encoding="utf-8")
    (tmp_path / "claims.json").write_text("[]", encoding="utf-8")

    summary = _build_generation_execution_summary(tmp_path)

    assert summary["status"] == "trace_missing"
    assert summary["root_cause"] == "generation_trace_missing"
