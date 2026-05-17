from src.agents.base_agent import AgentStatus, AgentTask
from src.agents.gap_resolver_agent import GapResolverAgent


def test_gap_resolver_flags_missing_statements_and_valuation_reason():
    agent = GapResolverAgent()
    result = agent.execute_task(
        AgentTask(
            task_id="gap",
            task_type="gap_resolver",
            description="detect gaps",
            parameters={
                "symbol": "TEST",
                "period": "2025Q4",
                "evidence_records": [{"evidence_id": "ev1", "source_type": "market"}],
                "claims": [],
                "markdown": "## 执行摘要\n公司业务增长。",
                "analysis_artifacts": {"tables": [], "valuation": {"valuation_available": False}},
                "search_meta": {"engine_meta": {"tavily": {"failure_reason": "missing_api_key"}}},
            },
        )
    )

    assert result.status == AgentStatus.COMPLETED
    summary = result.output["data_repair_summary"]
    assert summary["blocker_count"] >= 1
    assert "financial_statements" in result.output["required_backfill_sections"]
    assert "valuation" in result.output["required_backfill_sections"]
    assert summary["source_failure_count"] == 1


def test_gap_resolver_detects_statement_artifacts_not_in_body():
    agent = GapResolverAgent()
    result = agent.execute_task(
        AgentTask(
            task_id="gap",
            task_type="gap_resolver",
            description="detect gaps",
            parameters={
                "symbol": "TEST",
                "period": "2025Q4",
                "markdown": "## 财务分析\n公司盈利改善。",
                "analysis_artifacts": {
                    "tables": [
                        {"table_type": "income_statement"},
                        {"table_type": "balance_sheet"},
                        {"table_type": "cash_flow"},
                    ],
                    "valuation": {"valuation_available": True},
                },
            },
        )
    )

    gaps = result.output["gap_resolution_trace"]
    assert any(gap["gap_type"] == "three_statement_body" for gap in gaps)
