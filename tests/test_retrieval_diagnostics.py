from src.rag.retrieval_diagnostics import build_retrieval_coverage


def test_official_source_aliases_satisfy_required_market_sources():
    cn_coverage = build_retrieval_coverage(
        candidates=[{"source_type": "cninfo_announcement"}],
        returned=[{"source_type": "cninfo_announcement"}],
        company="600519.SS 贵州茅台",
    )
    assert cn_coverage["required_sources"] == ["cninfo"]
    assert cn_coverage["missing_sources"] == []
    assert cn_coverage["quality_ready"] is True

    hk_coverage = build_retrieval_coverage(
        candidates=[{"source_type": "hkex_annual_report"}],
        returned=[{"source_type": "hkex_annual_report"}],
        company="0700.HK 腾讯控股",
    )
    assert hk_coverage["required_sources"] == ["hkex"]
    assert hk_coverage["missing_sources"] == []
    assert hk_coverage["quality_ready"] is True

    for source_type in ["sec_companyfacts", "sec_filing"]:
        us_coverage = build_retrieval_coverage(
            candidates=[{"source_type": source_type}],
            returned=[{"source_type": source_type}],
            company="AAPL Apple Inc.",
        )
        assert us_coverage["required_sources"] == ["sec_edgar"]
        assert us_coverage["missing_sources"] == []
        assert us_coverage["quality_ready"] is True
