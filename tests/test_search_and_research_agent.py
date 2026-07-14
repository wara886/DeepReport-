import json
import time
import pandas as pd

import pytest

from src.agents import AgentStatus, AgentTask, DeepResearcherAgent
from src.search import SearchManager
from src.features.trend_analysis import build_trend_features
from src.search.search_manager import (
    adapt_financial_query,
    cninfo_announcement_search,
    eastmoney_financials_search,
    exchange_announcement_search,
    hkex_announcement_search,
    local_real_data_search,
    serper_search,
    tavily_search,
    yahoo_finance_search,
    _hk_statement_currency,
)


def test_hk_financial_statement_currency_uses_issuer_override():
    assert _hk_statement_currency("0700.HK", {"currency": "HKD"}) == "CNY"


def test_search_manager_keeps_three_hk_financial_tables_with_shared_url():
    manager = SearchManager()

    def hk_tables(query, topk=5, **kwargs):
        return {
            "hits": [
                {
                    "evidence_id": f"hk_{table_type}",
                    "title": f"0700.HK {table_type}",
                    "content": f"0700.HK {table_type}",
                    "source_url": "https://finance.yahoo.com/quote/0700.HK",
                    "source_type": "hk_financials",
                    "symbol": "0700.HK",
                    "score": 7.0,
                    "metadata": {"table_type": table_type},
                }
                for table_type in ("income", "balance", "cashflow")
            ]
        }

    manager.register_engine("hk_financials", hk_tables)
    payload = manager.search("Tencent FY2024", topk=5, engines=["hk_financials"], symbol="0700.HK")

    assert len(payload["hits"]) == 3
    assert {hit["raw"]["metadata"]["table_type"] for hit in payload["hits"]} == {"income", "balance", "cashflow"}


def _engine_a(query, topk=5, **kwargs):
    return {
        "hits": [
            {
                "sample_id": "ev_1",
                "title": "Apple filing",
                "content": "Revenue grew.",
                "source_url": "https://example.com/aapl",
                "score": 1.0,
                "source_type": "filing",
            }
        ],
        "meta": {"query": query, "topk": topk, "kwargs": kwargs},
    }


def _engine_b(query, topk=5, **kwargs):
    return {
        "hits": [
            {
                "sample_id": "ev_1_duplicate",
                "title": "Apple filing duplicate",
                "content": "Revenue grew duplicate.",
                "source_url": "https://example.com/aapl",
                "score": 0.5,
                "source_type": "filing",
            },
            {
                "sample_id": "ev_2",
                "title": "Apple news",
                "content": "Risk changed.",
                "source_url": "https://example.com/aapl-news",
                "score": 2.0,
                "source_type": "news",
            },
        ],
        "meta": {"query": query, "topk": topk, "kwargs": kwargs},
    }


def test_search_manager_dedupes_and_ranks_hits():
    manager = SearchManager()
    manager.register_engine("engine_a", _engine_a)
    manager.register_engine("engine_b", _engine_b)

    payload = manager.search("AAPL revenue", topk=5)

    assert payload["meta"]["total_hits_before_dedupe"] == 3
    assert payload["meta"]["returned_hits"] == 2
    assert payload["hits"][0]["result_id"] == "ev_1_duplicate"
    assert payload["hits"][0]["source_authority"] == "official"
    assert payload["hits"][1]["result_id"] == "ev_2"


def test_search_manager_prefers_richer_live_structured_record_over_stale_local_copy():
    manager = SearchManager()

    def stale_local(query, topk=5, **kwargs):
        return {
            "hits": [
                {
                    "evidence_id": "stale-sec-copy",
                    "source_type": "sec_companyfacts",
                    "source_url": "https://data.sec.gov/companyfacts/NVDA.json",
                    "content": "Assets only.",
                    "score": 0.9,
                    "metadata": {"parent_metadata": {"metrics": {"Assets": {"value": 1}}}},
                },
                {
                    "evidence_id": "stale-sec-chunk",
                    "chunk_id": "stale-sec-chunk",
                    "source_type": "sec_companyfacts",
                    "source_url": "https://data.sec.gov/companyfacts/NVDA.json",
                    "content": "Old vector chunk.",
                    "score": 1.0,
                },
            ],
            "meta": {},
        }

    def live_sec(query, topk=5, **kwargs):
        return {
            "hits": [
                {
                    "evidence_id": "live-sec-copy",
                    "source_type": "sec_companyfacts",
                    "source_url": "https://data.sec.gov/companyfacts/NVDA.json",
                    "content": "Current complete company facts.",
                    "score": 0.0,
                    "metadata": {
                        "metrics": {
                            "Assets": {"value": 1},
                            "Liabilities": {"value": 2},
                            "StockholdersEquity": {"value": 3},
                        }
                    },
                }
            ],
            "meta": {},
        }

    manager.register_engine("local_evidence", stale_local)
    manager.register_engine("sec_edgar", live_sec)

    payload = manager.search("NVDA FY2024", engines=["local_evidence", "sec_edgar"], topk=1, symbol="NVDA")

    assert len(payload["hits"]) == 1
    assert payload["hits"][0]["result_id"] == "live-sec-copy"
    assert len(payload["hits"][0]["raw"]["metadata"]["metrics"]) == 3


def test_search_manager_records_engine_duration_and_stops_after_budget():
    manager = SearchManager()

    def slow_engine(query, topk=5, **kwargs):
        time.sleep(0.02)
        return {"hits": [], "meta": {"source": "slow"}}

    manager.register_engine("slow", slow_engine)
    manager.register_engine("never_started", _engine_a)

    payload = manager.search(
        "AAPL revenue",
        engines=["slow", "never_started"],
        search_budget_seconds=0.005,
    )

    assert payload["meta"]["budget_exhausted"] is True
    assert payload["meta"]["skipped_engines"] == ["never_started"]
    assert payload["meta"]["engine_meta"]["slow"]["duration_ms"] >= 15


def test_search_manager_times_out_one_engine_and_continues():
    manager = SearchManager()

    def blocked_engine(query, topk=5, **kwargs):
        time.sleep(0.05)
        return {"hits": [], "meta": {}}

    manager.register_engine("blocked", blocked_engine)
    manager.register_engine("healthy", _engine_a)

    payload = manager.search(
        "AAPL revenue",
        engines=["blocked", "healthy"],
        engine_timeout_seconds=1.0,
        engine_timeout_by_name={"blocked": 0.005},
    )

    assert payload["meta"]["engine_meta"]["blocked"]["timeout"] is True
    assert payload["meta"]["engine_meta"]["blocked"]["timeout_seconds"] == 0.005
    assert payload["meta"]["engine_meta"]["healthy"]["hit_count"] > 0
    assert payload["hits"]


def test_trend_features_accept_mixed_missing_publish_times():
    features = build_trend_features(
        pd.DataFrame(
            [
                {"symbol": "MSFT", "period": "FY2024", "source_type": "sec", "publish_time": None, "sample_id": "a"},
                {"symbol": "MSFT", "period": "FY2024", "source_type": "web", "publish_time": "2024-07-30", "sample_id": "b"},
            ]
        )
    )

    assert features.iloc[0]["latest_publish_time"] == "2024-07-30"


def test_search_manager_reserves_yahoo_valuation_records():
    manager = SearchManager()

    def sec_engine(query, topk=5, **kwargs):
        return {
            "hits": [
                {
                    "sample_id": f"sec_{idx}",
                    "title": "Official filing",
                    "content": "Official revenue evidence.",
                    "source_url": f"https://sec.example/{idx}",
                    "source_type": "filing",
                    "score": 10.0 - idx,
                }
                for idx in range(4)
            ],
            "meta": {},
        }

    def yahoo_engine(query, topk=5, **kwargs):
        return {
            "hits": [
                {
                    "sample_id": "yahoo_snapshot",
                    "title": "Yahoo market snapshot",
                    "content": "Current price context.",
                    "source_url": "https://finance.yahoo.com/quote/AAPL",
                    "source_type": "market_api",
                    "score": 0.2,
                },
                {
                    "sample_id": "yahoo_financials",
                    "title": "Yahoo financial supplement",
                    "content": "marketCap=1000 trailingPE=20",
                    "source_url": "https://finance.yahoo.com/quote/AAPL/key-statistics",
                    "source_type": "market_api",
                    "score": 0.1,
                },
            ],
            "meta": {},
        }

    manager.register_engine("sec_edgar", sec_engine)
    manager.register_engine("yahoo_finance", yahoo_engine)
    payload = manager.search("AAPL FY2024 valuation", topk=4, symbol="AAPL", period="FY2024")

    result_ids = [item["result_id"] for item in payload["hits"]]
    assert "yahoo_snapshot" in result_ids
    assert "yahoo_financials" in result_ids


def test_deep_researcher_agent_uses_search_manager():
    manager = SearchManager()
    manager.register_engine("engine_a", _engine_a)
    agent = DeepResearcherAgent(search_manager=manager)
    task = AgentTask(
        task_id="task_001",
        task_type="deep_researcher",
        description="Find AAPL evidence.",
        parameters={"query": "AAPL revenue", "engines": ["engine_a"], "topk": 3},
    )

    result = agent.execute_task(task)

    assert result.status == AgentStatus.COMPLETED
    assert result.output["evidence_candidates"][0]["result_id"] == "ev_1"
    assert result.output["search_meta"]["engines"] == ["engine_a"]
    assert result.output["evidence_candidates"][0]["authority_score"] == 1.0


def test_deep_researcher_agent_splits_comma_separated_engines():
    manager = SearchManager()
    manager.register_engine("engine_a", _engine_a)
    manager.register_engine("engine_b", _engine_b)
    agent = DeepResearcherAgent(search_manager=manager)
    task = AgentTask(
        task_id="task_001",
        task_type="deep_researcher",
        description="Find AAPL evidence.",
        parameters={"query": "AAPL revenue", "engines": "engine_a,engine_b", "topk": 3},
    )

    result = agent.execute_task(task)

    assert result.status == AgentStatus.COMPLETED
    assert result.output["search_meta"]["engines"] == ["engine_a", "engine_b"]
    assert len(result.output["evidence_candidates"]) == 2


def test_financial_query_adapter_expands_chinese_finance_terms():
    info = adapt_financial_query(
        query="分析 Nvda 2025Q4 营收 毛利率 现金流 风险",
        symbol="NVDA",
        period="2025Q4",
        raw_data_root="data/raw/real_data",
    )

    assert info["query_expansion_version"] == "finance_query_expansion_v1"
    assert "NVIDIA Corporation" in info["query_terms_added"]
    assert "revenue" in info["query_adapted"]
    assert "gross margin" in info["query_adapted"]
    assert "cash flow" in info["query_adapted"]


def test_local_real_data_search_reports_adapted_query_and_failure_reason():
    payload = local_real_data_search(
        query="分析 Nvda 2025Q4 营收 毛利率",
        symbol="NVDA",
        period="2025Q4",
        raw_data_root="data/raw/real_data",
        topk=3,
    )

    assert payload["hits"]
    assert payload["meta"]["failure_reason"] == ""
    assert payload["meta"]["query_original"].startswith("分析 Nvda")
    assert "revenue" in payload["meta"]["query_adapted"]
    assert payload["meta"]["returned_hit_count"] >= 1


def test_local_real_data_profile_falls_back_without_cross_period_financials(tmp_path):
    symbol_dir = tmp_path / "TSLA"
    target_dir = symbol_dir / "2026Q1"
    prior_dir = symbol_dir / "2025Q4"
    target_dir.mkdir(parents=True)
    prior_dir.mkdir(parents=True)
    (target_dir / "financials.csv").write_text(
        "revenue_billion,revenue_growth_pct,gross_margin_pct,net_margin_pct,roe_pct,roa_pct,"
        "operating_cash_flow_billion,free_cash_flow_billion,notes\n"
        "22.387,0,0,0,0,0,2.16,0.15,target period\n",
        encoding="utf-8",
    )
    (prior_dir / "company_profile.json").write_text(
        json.dumps(
            {
                "business_summary": "Tesla designs electric vehicles and energy products.",
                "source_url": "https://example.com/profile",
            }
        ),
        encoding="utf-8",
    )
    (prior_dir / "financials.csv").write_text(
        "revenue_billion,revenue_growth_pct,gross_margin_pct,net_margin_pct,roe_pct,roa_pct,"
        "operating_cash_flow_billion,free_cash_flow_billion,notes\n"
        "999,0,0,0,0,0,0,0,prior period must not leak\n",
        encoding="utf-8",
    )

    payload = local_real_data_search(
        query="TSLA business revenue",
        symbol="TSLA",
        period="2026Q1",
        raw_data_root=str(tmp_path),
        topk=10,
    )

    profiles = [row for row in payload["hits"] if row["source_type"] == "company_profile"]
    financials = [row for row in payload["hits"] if row["source_type"] == "financials"]
    assert profiles
    assert profiles[0]["metadata"]["source_period"] == "2025Q4"
    assert profiles[0]["metadata"]["period_fallback"] is True
    assert any("22.387" in row["content"] for row in financials)
    assert all("999" not in row["content"] for row in financials)
    assert payload["meta"]["profile_period_fallback"] is True


def test_tavily_search_normalizes_response(monkeypatch, tmp_path):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")

    config_path = tmp_path / "data_sources.yaml"
    config_path.write_text(
        """
search:
  tavily:
    base_url: https://api.tavily.com/search
    api_key_env: TAVILY_API_KEY
    default_depth: basic
    max_results: 3
""".strip(),
        encoding="utf-8",
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"results":[{"title":"AAPL results","url":"https://example.com/aapl","content":"Revenue grew.","score":0.9}],"request_id":"req_1","response_time":"0.5"}'

    def fake_urlopen(req, timeout):
        assert req.get_header("Authorization") == "Bearer tvly-test"
        return FakeResponse()

    monkeypatch.setattr("src.search.search_manager.request.urlopen", fake_urlopen)

    payload = tavily_search(query="AAPL", topk=2, data_source_config_path=str(config_path))

    assert payload["meta"]["mode"] == "tavily"
    assert payload["hits"][0]["source_url"] == "https://example.com/aapl"
    assert payload["hits"][0]["source_type"] == "web_search"


def test_hkex_announcement_search_rejects_wrong_company_tavily_pdf(monkeypatch):
    monkeypatch.setattr(
        "src.search.search_manager.fetch_hkex_official_announcements",
        lambda **_kwargs: {"hits": [], "meta": {"failure_reason": "no_match"}},
    )
    def fake_tavily_search(**_kwargs):
        return {
            "hits": [
                {
                    "sample_id": "wrong_pdf",
                    "title": "[PDF] ANNUAL RESULTS FOR THE YEAR ENDED 31 MARCH 2025",
                    "content": "Century Entertainment International Holdings Limited annual results.",
                    "source_url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/annual-results.pdf",
                },
                {
                    "sample_id": "tencent_pdf",
                    "title": "Tencent Holdings Limited annual results announcement 2025",
                    "content": "Tencent Holdings Limited reports annual results and online games revenue.",
                    "source_url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2025/tencent.pdf",
                },
            ],
            "meta": {"mode": "tavily"},
        }

    monkeypatch.setattr("src.search.search_manager.tavily_search", fake_tavily_search)

    payload = hkex_announcement_search(query="Tencent annual report", symbol="0700.HK", period="FY2025", topk=5)

    assert [item["sample_id"] for item in payload["hits"]] == ["tencent_pdf"]
    assert payload["meta"]["identity_rejected_count"] == 1


def test_hkex_announcement_search_prefers_direct_official_source(monkeypatch):
    monkeypatch.setattr(
        "src.search.search_manager.fetch_hkex_official_announcements",
        lambda **_kwargs: {
            "hits": [{"evidence_id": "hk1", "sample_id": "hk1", "symbol": "0700.HK", "period": "FY2025", "title": "ANNUAL REPORT 2025", "content": "Official", "source_url": "https://www1.hkexnews.hk/a.pdf", "source_type": "hkex_announcement", "source_authority": "official"}],
            "meta": {"mode": "hkex_official", "result_count": 1},
        },
    )
    monkeypatch.setattr("src.search.search_manager.tavily_search", lambda **_kwargs: (_ for _ in ()).throw(AssertionError("fallback should not run")))

    payload = hkex_announcement_search(query="Tencent annual report", symbol="0700.HK", period="FY2025")

    assert payload["meta"]["mode"] == "hkex_official"
    assert payload["hits"][0]["evidence_id"] == "hk1"


def test_serper_search_normalizes_response(monkeypatch, tmp_path):
    monkeypatch.setenv("SERPER_API_KEY", "serper-test")

    config_path = tmp_path / "data_sources.yaml"
    config_path.write_text(
        """
search:
  serper:
    base_url: https://google.serper.dev/search
    api_key_env: SERPER_API_KEY
    gl: us
    hl: en
    max_results: 3
""".strip(),
        encoding="utf-8",
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"organic":[{"title":"NVDA results","link":"https://example.com/nvda","snippet":"Revenue grew.","position":1}],"searchParameters":{"q":"NVDA"}}'

    def fake_urlopen(req, timeout):
        assert req.get_header("X-api-key") == "serper-test"
        return FakeResponse()

    monkeypatch.setattr("src.search.search_manager.request.urlopen", fake_urlopen)

    payload = serper_search(query="NVDA", topk=2, data_source_config_path=str(config_path))

    assert payload["meta"]["mode"] == "serper"
    assert payload["hits"][0]["source_url"] == "https://example.com/nvda"
    assert payload["hits"][0]["source_type"] == "web_search"


@pytest.mark.skip(reason="metaso backend was intentionally removed")
def test_metaso_search_normalizes_response(monkeypatch, tmp_path):
    monkeypatch.setenv("METASO_API_KEY", "metaso-test")

    config_path = tmp_path / "data_sources.yaml"
    config_path.write_text(
        """
search:
  metaso:
    base_url: https://api.metaso.com/v1/search
    api_key_env: METASO_API_KEY
    language: zh-cn
    region: cn
    max_results: 3
""".strip(),
        encoding="utf-8",
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"results":[{"title":"AAPL filing","url":"https://example.com/aapl","description":"Revenue grew.","rank":1,"score":0.88}]}'

    def fake_urlopen(req, timeout):
        assert req.get_header("Authorization") == "Bearer metaso-test"
        return FakeResponse()

    monkeypatch.setattr("src.search.search_manager.request.urlopen", fake_urlopen)

    payload = metaso_search(query="AAPL 财报", topk=2, data_source_config_path=str(config_path))

    assert payload["meta"]["mode"] == "metaso"
    assert payload["hits"][0]["source_url"] == "https://example.com/aapl"
    assert payload["hits"][0]["source_type"] == "web_search"


@pytest.mark.skip(reason="sogou backend was intentionally removed")
def test_sogou_search_normalizes_response(monkeypatch, tmp_path):
    monkeypatch.setenv("SOGOU_API_KEY", "sogou-test")

    config_path = tmp_path / "data_sources.yaml"
    config_path.write_text(
        """
search:
  sogou:
    base_url: https://api.sogou.com/v1/search
    api_key_env: SOGOU_API_KEY
    language: zh-cn
    max_results: 3
""".strip(),
        encoding="utf-8",
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"items":[{"title":"AAPL annual report","url":"https://example.com/aapl.pdf","abstract":"Annual report PDF.","rank":1,"score":0.91}]}'

    def fake_urlopen(req, timeout):
        assert req.get_header("Authorization") == "Bearer sogou-test"
        return FakeResponse()

    monkeypatch.setattr("src.search.search_manager.request.urlopen", fake_urlopen)

    payload = sogou_search(query="AAPL annual report", topk=2, data_source_config_path=str(config_path))

    assert payload["meta"]["mode"] == "sogou"
    assert payload["hits"][0]["source_url"] == "https://example.com/aapl.pdf"
    assert payload["hits"][0]["source_type"] == "web_search"


def test_yahoo_finance_search_returns_market_api_evidence(monkeypatch):
    def fake_snapshot_to_evidence(symbol, period="", range_="1mo", interval="1d", timeout=12):
        return {
            "evidence_id": f"{symbol}_{period}_yahoo",
            "sample_id": f"{symbol}_{period}_yahoo",
            "symbol": symbol,
            "period": period,
            "source_type": "market_api",
            "title": f"{symbol} Yahoo Finance market snapshot",
            "content": "AAPL Yahoo Finance market snapshot: latest close 200.",
            "source_url": "https://finance.yahoo.com/quote/AAPL",
            "publish_time": "2026-04-25",
            "trust_level": "medium",
            "score": 2.4,
        }

    monkeypatch.setattr("src.search.search_manager.yahoo_snapshot_to_evidence", fake_snapshot_to_evidence)

    payload = yahoo_finance_search(query="AAPL market", symbol="AAPL", period="2025Q4")

    assert payload["meta"]["mode"] == "yahoo_finance"
    assert payload["hits"][0]["source_type"] == "market_api"
    assert payload["hits"][0]["source_url"] == "https://finance.yahoo.com/quote/AAPL"


def test_search_manager_registers_a_share_official_engines():
    engines = SearchManager.with_local_sources().engine_names()

    assert "cninfo_announcements" in engines
    assert "exchange_announcements" in engines
    assert "eastmoney_financials" in engines


def test_search_manager_keeps_distinct_eastmoney_statement_tables():
    manager = SearchManager()
    manager.register_engine(
        "fixture",
        lambda query, topk=5, **kwargs: {
            "hits": [
                {
                    "evidence_id": "income",
                    "source_type": "eastmoney_financials",
                    "title": "income",
                    "content": "income table",
                    "source_url": "https://data.eastmoney.com/bbsj/600519.html",
                    "score": 6.8,
                },
                {
                    "evidence_id": "balance",
                    "source_type": "eastmoney_financials",
                    "title": "balance",
                    "content": "balance table",
                    "source_url": "https://data.eastmoney.com/bbsj/600519.html",
                    "score": 6.8,
                },
            ],
            "meta": {},
        },
    )

    payload = manager.search("600519 财务表", topk=5)

    assert {hit["result_id"] for hit in payload["hits"]} == {"income", "balance"}


def test_cninfo_announcement_search_normalizes_official_reports(monkeypatch, tmp_path):
    config_path = tmp_path / "data_sources.yaml"
    config_path.write_text(
        """
independent_sources:
  company:
    cninfo:
      announcement_query_url: http://www.cninfo.com.cn/new/hisAnnouncement/query
      stock_list_url: http://www.cninfo.com.cn/new/data/szse_stock.json
      static_base_url: http://static.cninfo.com.cn/
      timeout: 5
      page_size: 5
      categories:
        - category_ndbg_szsh
""".strip(),
        encoding="utf-8",
    )

    class FakeResponse:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return self.body

    def fake_urlopen(req, timeout):
        if "szse_stock.json" in req.full_url:
            return FakeResponse(b'{"stockList":[{"code":"600519","orgId":"gssh0600519"}]}')
        assert b"category_ndbg_szsh" in req.data
        return FakeResponse(
            '{"announcements":[{"secCode":"600519","secName":"贵州茅台","announcementTitle":"2025年年度报告","adjunctUrl":"finalpage/2026-04-01/abc.pdf","announcementTime":"2026-04-01"}]}'.encode(
                "utf-8"
            )
        )

    monkeypatch.setattr("src.search.search_manager.request.urlopen", fake_urlopen)

    payload = cninfo_announcement_search(
        query="600519 年报",
        symbol="600519.SS",
        period="2025Q4",
        enable_remote=True,
        data_source_config_path=str(config_path),
    )

    assert payload["meta"]["failure_reason"] == ""
    assert payload["hits"][0]["source_type"] == "cninfo_announcement"
    assert payload["hits"][0]["source_url"].endswith("abc.pdf")
    assert payload["hits"][0]["source_authority"] == "official"


def test_exchange_announcement_search_normalizes_sse_response(monkeypatch, tmp_path):
    config_path = tmp_path / "data_sources.yaml"
    config_path.write_text(
        """
independent_sources:
  company:
    exchange_announcements:
      sse_query_url: https://query.sse.com.cn/security/stock/queryCompanyBulletin.do
      szse_announcement_url: https://www.szse.cn/api/disc/announcement/annList
      timeout: 5
      page_size: 5
""".strip(),
        encoding="utf-8",
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return '{"result":[{"TITLE":"贵州茅台2025年年度报告","URL":"/disclosure/listedinfo/announcement/c/new.pdf","SSEDATE":"2026-04-01"}]}'.encode(
                "utf-8"
            )

    def fake_urlopen(req, timeout):
        assert "productId=600519" in req.full_url
        return FakeResponse()

    monkeypatch.setattr("src.search.search_manager.request.urlopen", fake_urlopen)

    payload = exchange_announcement_search(
        query="600519 年报",
        symbol="600519.SS",
        period="2025Q4",
        enable_remote=True,
        data_source_config_path=str(config_path),
    )

    assert payload["meta"]["exchange"] == "sse"
    assert payload["hits"][0]["source_type"] == "exchange_announcement"
    assert payload["hits"][0]["source_authority"] == "official"


def test_eastmoney_financials_search_normalizes_statement_tables(monkeypatch, tmp_path):
    config_path = tmp_path / "data_sources.yaml"
    config_path.write_text(
        """
independent_sources:
  company:
    eastmoney_financials:
      base_url: https://datacenter-web.eastmoney.com/api/data/v1/get
      timeout: 5
      page_size: 5
      reports:
        income: RPT_DMSK_FN_INCOME
        balance: RPT_DMSK_FN_BALANCE
        cashflow: RPT_DMSK_FN_CASHFLOW
""".strip(),
        encoding="utf-8",
    )

    class FakeResponse:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return self.body

    def fake_urlopen(req, timeout):
        if "RPT_DMSK_FN_INCOME" in req.full_url:
            return FakeResponse(
                b'{"result":{"data":[{"SECURITY_CODE":"600519","REPORT_DATE":"2026-03-31","OPERATE_INCOME":54000000000},{"SECURITY_CODE":"600519","REPORT_DATE":"2025-12-31","OPERATE_INCOME":180000000000,"NETPROFIT":85000000000}]}}'
            )
        if "RPT_DMSK_FN_BALANCE" in req.full_url:
            return FakeResponse(b'{"result":{"data":[{"SECURITY_CODE":"600519","REPORT_DATE":"2025-12-31","TOTAL_ASSETS":300000000000}]}}')
        return FakeResponse(b'{"result":{"data":[{"SECURITY_CODE":"600519","REPORT_DATE":"2025-12-31","NETCASH_OPERATE":90000000000}]}}')

    monkeypatch.setattr("src.search.search_manager.request.urlopen", fake_urlopen)

    payload = eastmoney_financials_search(
        query="600519 财务表",
        symbol="600519.SS",
        period="2025Q4",
        enable_remote=True,
        data_source_config_path=str(config_path),
    )

    assert payload["meta"]["record_count"] == 3
    assert {hit["metadata"]["table_type"] for hit in payload["hits"]} == {"income", "balance", "cashflow"}
    assert all(hit["source_type"] == "eastmoney_financials" for hit in payload["hits"])
    income = next(hit for hit in payload["hits"] if hit["metadata"]["table_type"] == "income")
    assert "2025-12-31" in income["content"]
