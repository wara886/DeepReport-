import json
import time

from src.agents import AgentTask
from src.agents.deep_analyze_agent import DeepAnalyzeAgent, apply_evidence_gate
from src.agents.deep_analyze_agent import _normalize_valuation_tool_observation
from src.agents.deep_researcher_agent import DeepResearcherAgent, _select_evidence_candidates
from src.agents.react_loop import run_react_tool_loop
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
            parameters={
                "query": "AAPL revenue",
                "topk": 2,
                "symbol": "AAPL",
                "period": "2025Q4",
                "use_react": True,
                "merge_standard_search_after_react": False,
            },
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


class ScriptedReactModel:
    model_name = "scripted-react-model"

    def __init__(self, responses):
        self.responses = list(responses)

    def chat(self, **kwargs):
        return self.responses.pop(0)


def _tool_call(name, arguments, call_id="call_1"):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


def test_react_loop_returns_invalid_arguments_to_model_instead_of_crashing():
    model = ScriptedReactModel(
        [
            ModelResponse(success=True, tool_calls=[_tool_call("lookup", '{"query":"AAPL"')]),
            ModelResponse(success=True, content="Recovered after invalid arguments."),
        ]
    )

    result = run_react_tool_loop(
        model=model,
        system_prompt="test",
        user_prompt="test",
        tool_schemas=[{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}],
        handlers={"lookup": lambda **kwargs: {"ok": True}},
    )

    assert result["success"] is True
    assert result["status"] == "degraded"
    assert result["observations"][0]["result"]["error_type"] == "invalid_arguments"


def test_react_loop_recovers_invalid_json_when_required_arguments_are_bound():
    model = ScriptedReactModel(
        [
            ModelResponse(success=True, tool_calls=[_tool_call("lookup", '{"symbol":"AAPL"')]),
            ModelResponse(success=True, content="Recovered with bound arguments."),
        ]
    )

    result = run_react_tool_loop(
        model=model,
        system_prompt="test",
        user_prompt="test",
        tool_schemas=[{
            "type": "function",
            "function": {
                "name": "lookup",
                "parameters": {
                    "type": "object",
                    "properties": {"symbol": {"type": "string"}},
                    "required": ["symbol"],
                },
            },
        }],
        handlers={"lookup": lambda symbol: {"symbol": symbol, "ok": True}},
        bound_arguments={"lookup": {"symbol": "AAPL"}},
    )

    assert result["success"] is True
    assert result["observations"][0]["result"] == {"symbol": "AAPL", "ok": True}
    assert result["trace"][0]["error"] == ""


def test_unavailable_valuation_is_a_business_result_not_tool_error():
    normalized = _normalize_valuation_tool_observation(
        {"valuation_available": False, "error": "target financials not found"}
    )

    assert "error" not in normalized
    assert normalized["valuation_status"] == "target financials not found"
    assert normalized["unavailability_reason"] == "target financials not found"


def test_react_loop_marks_max_steps_as_failed():
    model = ScriptedReactModel(
        [ModelResponse(success=True, tool_calls=[_tool_call("lookup", "{}")])]
    )

    result = run_react_tool_loop(
        model=model,
        system_prompt="test",
        user_prompt="test",
        tool_schemas=[{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}],
        handlers={"lookup": lambda **kwargs: {"ok": True}},
        max_steps=1,
    )

    assert result["success"] is False
    assert result["status"] == "failed"
    assert result["error"] == "max_steps_reached"


def test_react_loop_retries_tool_and_locks_bound_arguments():
    calls = []

    def flaky_lookup(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError("temporary failure")
        return {"symbol": kwargs["symbol"]}

    model = ScriptedReactModel(
        [
            ModelResponse(
                success=True,
                tool_calls=[_tool_call("lookup", json.dumps({"query": "revenue", "symbol": "MSFT"}))],
            ),
            ModelResponse(success=True, content="done"),
        ]
    )
    schema = {
        "type": "function",
        "function": {
            "name": "lookup",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}, "symbol": {"type": "string"}},
                "required": ["query", "symbol"],
            },
        },
    }

    result = run_react_tool_loop(
        model=model,
        system_prompt="test",
        user_prompt="test",
        tool_schemas=[schema],
        handlers={"lookup": flaky_lookup},
        tool_max_attempts=2,
        bound_arguments={"lookup": {"symbol": "AAPL"}},
    )

    assert result["success"] is True
    assert result["observations"][0]["attempts"] == 2
    assert calls == [{"query": "revenue", "symbol": "AAPL"}] * 2


def test_react_loop_reports_tool_timeout():
    def slow_lookup(**kwargs):
        time.sleep(0.05)
        return {"ok": True}

    model = ScriptedReactModel(
        [
            ModelResponse(success=True, tool_calls=[_tool_call("lookup", "{}")]),
            ModelResponse(success=True, content="continue after timeout"),
        ]
    )

    result = run_react_tool_loop(
        model=model,
        system_prompt="test",
        user_prompt="test",
        tool_schemas=[{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}],
        handlers={"lookup": slow_lookup},
        tool_timeout_seconds=0.01,
        tool_max_attempts=1,
    )

    assert result["success"] is True
    assert result["status"] == "degraded"
    assert result["observations"][0]["result"]["error_type"] == "tool_timeout"


def test_research_react_merges_standard_search_by_default():
    class StubSearchManager:
        def search(self, **kwargs):
            return {
                "query": kwargs["query"],
                "hits": [
                    {
                        "result_id": "ev_standard",
                        "title": "SEC filing",
                        "snippet": "Official revenue disclosure.",
                        "url": "https://sec.gov/filing",
                        "source_type": "sec_edgar",
                        "score": 1.0,
                    }
                ],
                "meta": {"engines": ["sec_edgar"]},
            }

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="retrieve_local_evidence",
            description="Retrieve evidence.",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            handler=lambda **kwargs: {
                "hits": [
                    {
                        "result_id": "ev_react",
                        "title": "Local evidence",
                        "snippet": "Local revenue evidence.",
                        "url": "https://example.com/local",
                        "source_type": "local_evidence",
                        "score": 2.0,
                    }
                ]
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
    agent = DeepResearcherAgent(model=FakeReactModel(), search_manager=StubSearchManager(), tool_registry=registry)

    result = agent.execute_task(
        AgentTask(
            task_id="task_react_merge",
            task_type="deep_researcher",
            description="Find AAPL evidence",
            parameters={"query": "AAPL revenue", "topk": 5, "symbol": "AAPL", "period": "FY2024", "use_react": True},
        )
    )

    assert result.metadata["standard_search_merged"] is True
    assert {item["result_id"] for item in result.output["evidence_candidates"]} == {"ev_react", "ev_standard"}


def test_research_candidate_selection_preserves_financial_and_market_roles():
    local_rows = [
        {
            "result_id": f"local_{index}",
            "title": "Local filing chunk",
            "url": f"https://example.com/{index}",
        }
        for index in range(8)
    ]
    financial = {
        "result_id": "yahoo_financials",
        "title": "AAPL Yahoo Finance financial data",
        "url": "https://finance.yahoo.com/quote/AAPL/key-statistics",
        "raw": {"metadata": {"context_type": "period_matched_financial_supplement"}},
    }
    snapshot = {
        "result_id": "yahoo_snapshot",
        "title": "AAPL Yahoo Finance market snapshot",
        "url": "https://finance.yahoo.com/quote/AAPL",
        "raw": {
            "metadata": {
                "parent_metadata": {"context_type": "current_market_snapshot"},
            }
        },
    }

    selected = _select_evidence_candidates([*local_rows, financial, snapshot], topk=4)

    assert len(selected) == 4
    assert {item["result_id"] for item in selected} >= {"yahoo_financials", "yahoo_snapshot"}


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
