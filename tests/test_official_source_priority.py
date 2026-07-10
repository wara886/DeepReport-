from src.search import SearchManager


def test_search_manager_prioritizes_official_sources_over_higher_scored_market_data():
    manager = SearchManager()
    manager.register_engine(
        "fixture",
        lambda query, topk=5, **kwargs: {
            "hits": [
                {
                    "evidence_id": "ev_market",
                    "title": "AAPL market snapshot",
                    "content": "AAPL market data estimate.",
                    "source_type": "market_api",
                    "source_url": "https://finance.yahoo.com/quote/AAPL",
                    "score": 9.9,
                },
                {
                    "evidence_id": "ev_sec",
                    "title": "AAPL FY2024 10-K",
                    "content": "Apple filed FY2024 revenue and net income.",
                    "source_type": "sec_edgar",
                    "source_url": "https://www.sec.gov/Archives/edgar/data/320193/aapl-20240928.htm",
                    "score": 0.5,
                },
                {
                    "evidence_id": "ev_news",
                    "title": "AAPL news commentary",
                    "content": "News commentary about demand.",
                    "source_type": "news",
                    "source_url": "https://example.com/aapl-news",
                    "score": 8.0,
                },
            ]
        },
    )

    payload = manager.search("AAPL FY2024 revenue", topk=3)

    assert [hit["result_id"] for hit in payload["hits"]] == ["ev_sec", "ev_market", "ev_news"]
    assert payload["hits"][0]["source_authority"] == "official"
    assert payload["hits"][0]["authority_score"] == 1.0


def test_search_manager_keeps_official_source_priority_after_deduplication():
    manager = SearchManager()
    manager.register_engine(
        "fixture",
        lambda query, topk=5, **kwargs: {
            "hits": [
                {
                    "evidence_id": "ev_market_duplicate",
                    "chunk_id": "aapl-revenue",
                    "title": "AAPL duplicate market data",
                    "content": "Revenue estimate from market data.",
                    "source_type": "market_api",
                    "source_url": "https://example.com/aapl-revenue",
                    "score": 10.0,
                },
                {
                    "evidence_id": "ev_official_duplicate",
                    "chunk_id": "aapl-revenue",
                    "title": "AAPL duplicate official filing",
                    "content": "Revenue from official filing.",
                    "source_type": "official_filing",
                    "source_url": "https://www.sec.gov/Archives/edgar/data/320193/aapl-20240928.htm",
                    "score": 1.0,
                },
            ]
        },
    )

    payload = manager.search("AAPL revenue", topk=1)

    assert payload["hits"][0]["result_id"] == "ev_official_duplicate"
    assert payload["hits"][0]["source_authority"] == "official"
