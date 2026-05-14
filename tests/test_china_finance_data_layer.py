from src.data.china_finance import china_finance_source_map, normalize_china_symbol
from src.data.source_authority import grade_source_authority
from src.search import SearchManager
from src.search.search_manager import china_finance_search
from src.tools import build_core_tool_registry


def test_normalize_china_symbol_handles_a_share_and_h_share():
    assert normalize_china_symbol("600519")["normalized_symbol"] == "600519.SH"
    assert normalize_china_symbol("000001.SZ")["exchange"] == "SZSE"
    assert normalize_china_symbol("00700.HK")["normalized_symbol"] == "00700.HK"


def test_china_finance_source_map_returns_official_a_share_sources():
    records = china_finance_source_map("600519", period="latest")

    urls = {record["source_url"] for record in records}
    assert "https://www.cninfo.com.cn/new/snapshot/companyListCn" in urls
    assert any("sse.com.cn" in url for url in urls)

    official = next(record for record in records if "cninfo.com.cn" in record["source_url"])
    grade = grade_source_authority(official)
    assert grade["source_authority"] == "official"
    assert grade["authority_level"] == "primary"


def test_china_finance_source_map_separates_market_data_sources():
    records = china_finance_source_map("000001.SZ", include_market_sources=True)
    market = next(record for record in records if "eastmoney.com" in record["source_url"])

    grade = grade_source_authority(market)
    assert grade["source_authority"] == "market_data"
    assert grade["authority_level"] == "market_data"
    assert "market_price" in grade["allowed_claim_types"]
    assert "revenue" not in grade["allowed_claim_types"]


def test_china_finance_search_is_registered_in_local_sources():
    manager = SearchManager.with_local_sources()

    payload = manager.search("贵州茅台 600519 年报", topk=3, engines=["china_finance"])

    assert payload["meta"]["engine_meta"]["china_finance"]["symbol"] == "600519.SH"
    assert payload["hits"]
    assert payload["hits"][0]["source_authority"] in {"official", "market_data"}


def test_china_finance_search_handles_h_share():
    payload = china_finance_search(query="腾讯控股 00700.HK 公告", topk=5)

    assert payload["meta"]["symbol"] == "00700.HK"
    assert any("hkexnews.hk" in item["source_url"] for item in payload["hits"])


def test_china_finance_tool_returns_source_candidates():
    registry = build_core_tool_registry()

    result = registry.call("discover_china_finance_sources", symbol="600519", period="latest")

    assert result["count"] >= 2
    assert any("cninfo.com.cn" in item["source_url"] for item in result["evidence"])
