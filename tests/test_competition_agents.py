from src.agents import AgentStatus, AgentTask, IndustryResearchAgent, MacroResearchAgent


def _evidence_records():
    return [
        {
            "evidence_id": "ev_profile",
            "source_type": "company_profile",
            "content": "Apple designs consumer electronics and services.",
            "metadata": {"sector": "Technology", "industry": "Consumer Electronics"},
        },
        {
            "evidence_id": "ev_market",
            "source_type": "market_api",
            "content": "Market snapshot for AAPL.",
            "metadata": {},
        },
    ]


def _independent_records():
    return [
        {
            "evidence_id": "fred_fedfunds",
            "source_type": "fred_series",
            "evidence_scope": "macro",
            "content": "Effective Federal Funds Rate latest observation is 4.33.",
            "source_timestamp": "2026-04-01",
            "data_cutoff": "2026-04-01",
            "freshness_bucket": "fresh",
            "metadata": {},
        }
    ]


def test_industry_research_agent_generates_non_placeholder_report():
    agent = IndustryResearchAgent()

    result = agent.execute_task(
        AgentTask(
            task_id="industry",
            task_type="industry_research",
            description="Industry report",
            parameters={
                "symbol": "AAPL",
                "period": "2025Q4",
                "company_summary": {"evidence_count": 2, "claim_count": 3, "company_report_overall_score": 0.9},
                "evidence_records": _evidence_records(),
                "claims": [{"claim_id": "cl_1"}],
                "analysis_artifacts": {"peer_context": {"peer_count": 4}},
            },
        )
    )

    markdown = result.output["markdown"]
    assert result.status == AgentStatus.COMPLETED
    assert "IndustryResearchAgent" in markdown
    assert "Consumer Electronics" in markdown
    assert "尚未在当前 checkout 中接入" not in markdown
    assert result.output["report_json"]["peer_count"] == 4


def test_industry_research_agent_reports_independent_source_boundary():
    agent = IndustryResearchAgent()

    result = agent.execute_task(
        AgentTask(
            task_id="industry",
            task_type="industry_research",
            description="Industry report",
            parameters={
                "symbol": "AAPL",
                "period": "2025Q4",
                "evidence_records": _evidence_records(),
                "independent_evidence_records": _independent_records(),
                "independent_source_meta": {"enabled": True},
            },
        )
    )

    assert result.output["report_json"]["independent_evidence_count"] == 1
    assert "真实边界" in result.output["markdown"]
    assert "fred_fedfunds" in result.output["report_json"]["independent_source_evidence_ids"]


def test_macro_research_agent_generates_transmission_report():
    agent = MacroResearchAgent()

    result = agent.execute_task(
        AgentTask(
            task_id="macro",
            task_type="macro_research",
            description="Macro report",
            parameters={
                "symbol": "AAPL",
                "period": "2025Q4",
                "company_summary": {"verification_passed": True, "multimodal_consistency_passed": True},
                "evidence_records": _evidence_records(),
                "claims": [{"claim_id": "cl_1"}],
            },
        )
    )

    markdown = result.output["markdown"]
    assert result.status == AgentStatus.COMPLETED
    assert "MacroResearchAgent" in markdown
    assert "利率与流动性" in markdown
    assert "尚未接入专用 MacroResearchAgent" not in markdown
    assert result.output["report_json"]["market_evidence_ids"] == ["ev_market"]


def test_macro_research_agent_uses_independent_macro_evidence_ids():
    agent = MacroResearchAgent()

    result = agent.execute_task(
        AgentTask(
            task_id="macro",
            task_type="macro_research",
            description="Macro report",
            parameters={
                "symbol": "AAPL",
                "period": "2025Q4",
                "evidence_records": _evidence_records(),
                "independent_evidence_records": _independent_records(),
                "independent_source_meta": {"enabled": True},
            },
        )
    )

    assert result.output["report_json"]["independent_evidence_count"] == 1
    assert result.output["report_json"]["macro_evidence_ids"] == ["fred_fedfunds"]
    assert "数据边界与时效" in result.output["markdown"]
