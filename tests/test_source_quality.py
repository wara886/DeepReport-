from src.data.source_quality import apply_source_quality


def test_eastmoney_financials_is_not_official_source():
    row = apply_source_quality(
        {
            "source_type": "eastmoney_financials",
            "source_url": "https://data.eastmoney.com/bbsj/600519.html",
            "title": "600519 Eastmoney income financial table",
        }
    )

    assert row["source_authority"] == "third_party_structured"
    assert row["authority_level"] == "market_data"
    assert row["trust_level"] == "medium"


def test_cninfo_pdf_remains_official_source():
    row = apply_source_quality(
        {
            "source_type": "cninfo_announcement",
            "source_url": "https://www.cninfo.com.cn/new/disclosure/detail",
            "title": "贵州茅台年度报告 PDF",
        }
    )

    assert row["source_authority"] == "official"
    assert row["authority_level"] == "primary"
