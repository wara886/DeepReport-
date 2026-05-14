from src.agents.base_agent import AgentTask
from src.agents.peer_comparison_agent import PeerComparisonAgent
from src.agents.risk_agent import RiskAgent
from src.features.company_valuation import build_peer_comparison, perform_company_valuation
from src.report.citation_manager import build_citations
from src.search.search_manager import local_real_data_search


def test_a_share_local_financials_support_report_metrics():
    payload = local_real_data_search(
        query="贵州茅台 营收 现金流",
        symbol="600519.SS",
        period="latest",
        topk=5,
        use_chunks=False,
    )

    assert payload["hits"]
    assert payload["meta"]["symbol"] == "600519.SS"
    assert any(item["source_type"] == "financials" for item in payload["hits"])

    valuation = perform_company_valuation(symbol="600519.SS", period="latest", records=payload["hits"])
    assert valuation["valuation_available"] is True
    assert valuation["currency"] == "CNY_billion"


def test_a_share_peer_comparison_uses_liquor_peer_universe():
    peers = build_peer_comparison(symbol="600519.SS", period="latest")

    assert peers["peer_count"] >= 2
    assert {"000858.SZ", "000568.SZ", "600809.SH"}.issubset(
        {row["symbol"] for row in peers["peer_rows"]}
    )


def test_a_share_peer_agent_does_not_emit_sec_methodology():
    result = PeerComparisonAgent().run(
        AgentTask(
            task_id="peer",
            task_type="peer_compare",
            description="A-share peer compare",
            parameters={
                "symbol": "600519.SS",
                "period": "latest",
                "sector": "Consumer Staples / 食品饮料",
                "industry": "白酒",
                "target_metrics": {
                    "symbol": "600519.SS",
                    "period": "latest",
                    "revenue_billion": 53.91,
                    "revenue_growth_pct": 6.54,
                    "net_margin_pct": 50.53,
                },
                "financial_evidence_ids": ["600519.SS_latest_financials"],
                "raw_data_root": "data/raw/real_data",
                "use_sec_fetch": False,
            },
        )
    )

    claim_text = result.output["claims"][0]["claim_text"]
    assert "核心可比组 000858.SZ, 000568.SZ, 600809.SH" in claim_text
    assert "SEC EDGAR" not in claim_text
    assert "A/H 股同行数据" in claim_text
    assert result.output["evidence_records"]


def test_a_share_risk_agent_uses_china_filing_language():
    result = RiskAgent().run(
        AgentTask(
            task_id="risk",
            task_type="risk",
            description="A-share risk",
            parameters={
                "symbol": "600519.SS",
                "evidence_records": [{"title": "贵州茅台 年报", "content": "白酒 渠道"}],
                "ratio_rows": [{"sector": "Consumer Staples / 食品饮料", "industry": "白酒"}],
                "valuation": {},
            },
        )
    )

    claim_text = result.output["claims"][0]["claim_text"]
    assert "10-Q/10-K" not in claim_text
    assert "交易所公告" in claim_text or "年报、季报" in claim_text


def test_citation_manager_does_not_flag_official_or_market_data_as_weak():
    citations = build_citations(
        evidence_records=[
            {
                "evidence_id": "cninfo_1",
                "source_type": "filing",
                "source_authority": "official",
                "authority_level": "primary",
                "authority_score": 1.0,
                "source_url": "https://static.cninfo.com.cn/finalpage/report.pdf",
            },
            {
                "evidence_id": "eastmoney_1",
                "source_type": "market_data",
                "source_authority": "market_data",
                "authority_level": "market_data",
                "authority_score": 0.78,
                "source_url": "https://quote.eastmoney.com/sh600519.html",
            },
        ],
        claims=[
            {"claim_id": "cl_1", "section_name": "financial_analysis", "evidence_ids": ["cninfo_1"]},
            {"claim_id": "cl_2", "section_name": "market", "evidence_ids": ["eastmoney_1"]},
        ],
    )

    assert not any(item.get("is_weak_source") for item in citations)
