import json

from src.agents import AgentTask
from src.agents.deep_analyze_agent import DeepAnalyzeAgent, apply_evidence_gate
from src.agents.deep_researcher_agent import DeepResearcherAgent
from src.models import ModelResponse
from src.schemas.claim import ClaimItem
from src.tools import ToolRegistry, ToolSpec


class FakeReactModel:
    model_name = "fake-react-model"

    def __init__(self):
        self.calls = 0

    def chat(self, messages, tools=None, tool_choice=None, **kwargs):
        self.calls += 1
        assert tools
        assert tool_choice == "auto"
        if self.calls == 1:
            return ModelResponse(
                success=True,
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "retrieve_local_evidence",
                            "arguments": json.dumps({"query": "AAPL revenue", "topk": 2}),
                        },
                    }
                ],
            )
        assert any(message["role"] == "tool" for message in messages)
        return ModelResponse(success=True, content="Enough evidence collected.")


class FakeAnalyzeReactModel:
    model_name = "fake-analyze-react-model"

    def __init__(self):
        self.calls = 0

    def chat(self, messages, tools=None, tool_choice=None, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                success=True,
                tool_calls=[
                    {
                        "id": "ratio_call",
                        "type": "function",
                        "function": {"name": "calculate_financial_ratios", "arguments": "{}"},
                    },
                    {
                        "id": "statement_call",
                        "type": "function",
                        "function": {"name": "build_three_statement_view", "arguments": "{}"},
                    },
                    {
                        "id": "peer_call",
                        "type": "function",
                        "function": {"name": "build_peer_comparison", "arguments": "{}"},
                    },
                    {
                        "id": "valuation_call",
                        "type": "function",
                        "function": {"name": "perform_company_valuation", "arguments": "{}"},
                    },
                ],
            )
        return ModelResponse(success=True, content="Analysis tools complete.")


def test_deep_researcher_can_use_react_tool_loop_before_search_fallback():
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="retrieve_local_evidence",
            description="Retrieve evidence.",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}},
            handler=lambda **kwargs: {
                "hits": [
                    {
                        "result_id": "ev_react",
                        "title": "AAPL financials",
                        "snippet": "Revenue 126.3B.",
                        "url": "https://example.com/aapl",
                        "source_type": "financials",
                        "score": 2.0,
                    }
                ],
                "meta": {"mode": "test"},
            },
        )
    )
    registry.register(
        ToolSpec(
            name="fetch_yahoo_market_snapshot",
            description="Fetch market snapshot.",
            parameters={"type": "object", "properties": {"symbol": {"type": "string"}}},
            handler=lambda **kwargs: {"evidence": {}},
        )
    )
    agent = DeepResearcherAgent(model=FakeReactModel(), tool_registry=registry)

    result = agent.execute_task(
        AgentTask(
            task_id="task_react",
            task_type="deep_researcher",
            description="Find AAPL evidence",
            parameters={"query": "AAPL revenue", "topk": 2, "symbol": "AAPL", "period": "2025Q4", "use_react": True},
        )
    )

    assert result.metadata["react_used"] is True
    assert result.metadata["react_trace"][0]["tool_name"] == "retrieve_local_evidence"
    assert result.output["evidence_candidates"][0]["result_id"] == "ev_react"
    assert result.output["search_meta"]["engines"] == ["react_tool_loop"]


def test_deep_analyze_can_use_react_tools_for_financial_artifacts():
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="calculate_financial_ratios",
            description="Ratios.",
            parameters={"type": "object", "properties": {}},
            handler=lambda records: {
                "rows": [
                    {
                        "sample_id": "ev_fin",
                        "symbol": "AAPL",
                        "revenue_billion": 126.3,
                        "gross_margin_pct": 46.8,
                        "operating_cash_flow_billion": 38.1,
                    }
                ]
            },
        )
    )
    registry.register(
        ToolSpec(
            name="build_trend_features",
            description="Trends.",
            parameters={"type": "object", "properties": {}},
            handler=lambda records: {"rows": []},
        )
    )
    registry.register(
        ToolSpec(
            name="build_three_statement_view",
            description="Statements.",
            parameters={"type": "object", "properties": {}},
            handler=lambda records: {"coverage": {"has_three_statement_view": True, "line_item_count": 3}, "rows": []},
        )
    )
    registry.register(
        ToolSpec(
            name="build_peer_comparison",
            description="Peers.",
            parameters={"type": "object", "properties": {}},
            handler=lambda symbol, period, raw_data_root="data/raw/real_data": {"target_symbol": symbol, "peer_count": 0, "ranking": {}},
        )
    )
    registry.register(
        ToolSpec(
            name="perform_company_valuation",
            description="Valuation.",
            parameters={"type": "object", "properties": {}},
            handler=lambda symbol, period, records=None, raw_data_root="data/raw/real_data": {"valuation_available": False},
        )
    )
    agent = DeepAnalyzeAgent(model=FakeAnalyzeReactModel(), tool_registry=registry)

    result = agent.execute_task(
        AgentTask(
            task_id="task_analyze_react",
            task_type="deep_analyze",
            description="Analyze AAPL",
            parameters={
                "symbol": "AAPL",
                "period": "2025Q4",
                "use_react": True,
                "evidence_records": [
                    {
                        "evidence_id": "ev_fin",
                        "sample_id": "ev_fin",
                        "symbol": "AAPL",
                        "period": "2025Q4",
                        "source_type": "financials",
                        "content": "Revenue 126.3B, gross margin 46.8%, operating cash flow 38.1B.",
                    }
                ],
            },
        )
    )

    assert result.metadata["react_used"] is True
    assert {item["tool_name"] for item in result.metadata["react_trace"]} >= {
        "calculate_financial_ratios",
        "build_three_statement_view",
        "build_peer_comparison",
        "perform_company_valuation",
    }
    assert result.output["analysis_artifacts"]["ratio_rows"][0]["revenue_billion"] == 126.3
    assert result.output["claims"]


def test_analyze_evidence_gate_rejects_unsupported_numeric_claims():
    evidence = [
        {
            "evidence_id": "ev_fin",
            "sample_id": "ev_fin",
            "content": "Revenue 126.3B and gross margin 46.8%.",
            "numeric_values": {"revenue_billion": 126.3, "gross_margin_pct": 46.8},
        }
    ]
    claims = [
        ClaimItem(
            claim_id="cl_good",
            section_name="financial_analysis",
            claim_text="Revenue was 126.3B.",
            evidence_ids=["ev_fin"],
            numeric_values={"revenue_billion": 126.3},
            confidence=0.9,
        ),
        ClaimItem(
            claim_id="cl_bad",
            section_name="financial_analysis",
            claim_text="Revenue was 395.4B.",
            evidence_ids=["ev_fin"],
            numeric_values={"revenue_billion": 395.4},
            confidence=0.9,
        ),
        ClaimItem(
            claim_id="cl_missing",
            section_name="financial_analysis",
            claim_text="Cash flow was 124.3B.",
            evidence_ids=[],
            numeric_values={"operating_cash_flow_billion": 124.3},
            confidence=0.8,
        ),
    ]

    accepted, report = apply_evidence_gate(claims=claims, evidence_records=evidence)

    assert [claim.claim_text for claim in accepted] == ["Revenue was 126.3B."]
    assert report["accepted_claim_count"] == 1
    assert report["rejected_claim_count"] == 2
    assert any("unsupported_numeric_values" in ",".join(item["reasons"]) for item in report["rejected_claims"])
