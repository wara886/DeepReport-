from pathlib import Path

from src.agents.multi_agent_orchestrator import MultiAgentOrchestrator
from src.agents.request_understanding_agent import RequestUnderstandingAgent
from src.request_understanding.entity_resolver import EntityResolver
from src.request_understanding.eval import evaluate_request_understanding_cases, load_request_understanding_cases
from src.request_understanding.schema import normalize_structured_request


class FakeModel:
    model_name = "fake"

    def generate_json(self, *args, **kwargs):
        return {}


def test_request_understanding_parses_nvda_latest_quarter():
    request = RequestUnderstandingAgent(model=None).parse("分析英伟达最近一个季度的经营情况，判断当前估值是否偏贵，并给出主要风险。")

    assert request.resolved_entity.symbol == "NVDA"
    assert request.resolved_entity.market == "US"
    assert request.period.type == "latest_quarter"
    assert request.report_type == "company_research"
    assert "估值" in request.focus_areas
    assert request.clarification_needed is False


def test_request_understanding_parses_moutai_deep_report():
    request = RequestUnderstandingAgent(model=None).parse("帮我生成一份贵州茅台的最新深度金融研报，重点关注盈利质量、估值、行业风险和同业对比。")

    assert request.resolved_entity.symbol == "600519.SS"
    assert request.resolved_entity.market == "CN-A"
    assert request.report_type == "deep_company_research"
    assert request.output_preferences.depth == "deep"
    assert {"盈利质量", "估值", "行业风险", "同业对比"}.issubset(set(request.focus_areas))
    assert request.attachments.optional is True


def test_entity_resolver_flags_cmb_a_h_ambiguity():
    result = EntityResolver().resolve("给我一份招商银行研报，关注净息差、资产质量和估值。")

    assert result.ambiguous is True
    assert {item["symbol"] for item in result.candidates} >= {"600036.SS", "3968.HK"}


def test_request_understanding_clarifies_ambiguous_apple_product():
    request = RequestUnderstandingAgent(model=None).parse("帮我做一个苹果分析，看看最近表现和风险。")

    assert request.clarification_needed is True
    assert request.clarification_questions
    assert any("Apple" in str(item.get("company_name")) for item in request.resolved_entity.candidates)


def test_request_understanding_parses_tencent_hk_valuation():
    request = RequestUnderstandingAgent(model=None).parse("分析腾讯估值。")

    assert request.resolved_entity.symbol == "0700.HK"
    assert request.resolved_entity.market == "HK"
    assert request.report_type == "valuation_analysis"
    assert request.clarification_needed is False


def test_structured_request_keeps_cli_eval_mode():
    request = normalize_structured_request(
        {
            "original_query": "AAPL regression case",
            "symbol": "AAPL",
            "company_name": "Apple Inc.",
            "market": "US",
            "period": "2025Q4",
            "report_type": "company_research",
            "focus_areas": ["financials"],
        }
    )

    assert request.symbol == "AAPL"
    assert request.period.type == "2025Q4"
    assert request.clarification_needed is False


def test_request_understanding_eval_metrics_cover_cases():
    cases = load_request_understanding_cases(Path("/Users/yuan_dian/AI_project/DeepReport_plus/eval/request_understanding/cases.jsonl"))

    summary = evaluate_request_understanding_cases(cases, agent=RequestUnderstandingAgent(model=None))

    assert summary["case_count"] == 5
    assert summary["entity_resolution_accuracy"] >= 0.8
    assert summary["report_type_accuracy"] >= 0.8
    assert summary["period_parse_accuracy"] == 1.0
    assert summary["clarification_precision"] == 1.0
    assert summary["clarification_recall"] == 1.0


def test_orchestrator_natural_language_entry_returns_clarification_without_running_report(tmp_path: Path):
    orchestrator = MultiAgentOrchestrator(output_dir=str(tmp_path / "outputs"), report_dir=str(tmp_path / "reports"), model=FakeModel())

    result = orchestrator.run(natural_language_query="给我一份招商银行研报，关注净息差、资产质量和估值。")

    assert result["status"] == "clarification_needed"
    assert Path(result["request_understanding"]).exists()


def test_orchestrator_structured_request_builds_research_request_without_clarification(tmp_path: Path):
    orchestrator = MultiAgentOrchestrator(output_dir=str(tmp_path / "outputs"), report_dir=str(tmp_path / "reports"), model=FakeModel())
    request = orchestrator._build_research_request(
        research_topic="",
        symbol="AAPL",
        period="2025Q4",
        natural_language_query=None,
        structured_request={
            "original_query": "AAPL regression",
            "symbol": "AAPL",
            "company_name": "Apple Inc.",
            "market": "US",
            "period": "2025Q4",
            "report_type": "company_research",
        },
        attachments=[],
    )

    assert request.symbol == "AAPL"
    assert request.clarification_needed is False
