from src.agents import AgentStatus, AgentTask, DeepResearcherAgent
from src.search import SearchManager
from src.search.search_manager import adapt_financial_query, local_real_data_search, metaso_search, serper_search, sogou_search, tavily_search, yahoo_finance_search


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
    assert payload["hits"][0]["result_id"] == "ev_2"
    assert payload["hits"][1]["result_id"] == "ev_1"
    assert payload["hits"][1]["source_authority"] == "official"


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
