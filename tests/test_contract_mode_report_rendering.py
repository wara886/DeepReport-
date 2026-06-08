from src.agents.base_agent import AgentStatus, TaskResult
from src.agents import multi_agent_orchestrator as orchestrator_module


def test_contract_mode_uses_professional_html_and_citation_map(tmp_path, monkeypatch):
    monkeypatch.setattr(
        orchestrator_module,
        "generate_report_charts",
        lambda **kwargs: [
            {
                "chart_id": "financial_scale_bar",
                "title": "财务规模",
                "chart_js": {
                    "type": "bar",
                    "labels": ["收入", "净利润", "经营现金流"],
                    "data": [1720.5, 823.2, 615.2],
                    "label": "亿元人民币",
                    "unit_label": "亿元人民币",
                },
            }
        ],
    )

    state = {
        "symbol": "600519.SS",
        "period": "2026Q1",
        "chart_output_dir": str(tmp_path),
        "entity_resolution": {"company_name": "贵州茅台"},
        "claims": [{"claim_id": "cl_001", "evidence_ids": ["ev_annual"]}],
        "evidence_records": [
            {
                "evidence_id": "ev_annual",
                "title": "贵州茅台 2026Q1 公告",
                "source_url": "https://example.com/600519-q1.pdf",
                "source_type": "annual_report_pdf",
                "content": "官方公告披露收入、净利润和经营现金流。",
            }
        ],
        "analysis_artifacts": {},
    }
    result = TaskResult(
        task_id="final",
        agent_name="FinalAnswerAgent",
        status=AgentStatus.COMPLETED,
        output={
            "markdown": "# 贵州茅台 2026Q1 研报\n\n官方公告支持核心结论 [1]。",
            "html": "<html><body><h1>fallback</h1></body></html>",
            "report_json": {"title": "贵州茅台 2026Q1 研报"},
        },
        metadata={"contract_mode": True, "citation_map": {"ev_annual": 1}},
    )

    orchestrator_module.merge_task_result(state, "final_answer", result)

    assert state["citations"]
    assert state["citations"][0]["evidence_id"] == "ev_annual"
    assert "chartPayloads" in state["html"]
    assert "https://cdn.jsdelivr.net/npm/chart.js" in state["html"]
    assert "交互图表" in state["html"]
    assert "暂无结构化引用" not in state["markdown"]
