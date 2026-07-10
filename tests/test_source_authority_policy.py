from src.agents.verifier import Verifier
from src.data.source_authority import can_support_claim, grade_source_authority
from src.schemas.claim import ClaimItem


def test_source_authority_policy_marks_official_filings_as_primary():
    grade = grade_source_authority(
        {
            "source_type": "filing",
            "source_url": "https://www.sec.gov/Archives/edgar/data/0000320193/10-q.htm",
            "title": "AAPL 10-Q",
        }
    )

    assert grade["source_authority"] == "official"
    assert grade["authority_level"] == "primary"
    assert grade["source_document_type"] == "10-Q"
    assert "revenue" in grade["allowed_claim_types"]
    assert can_support_claim({"source_type": "filing", "source_url": "https://www.sec.gov/aapl"}, "revenue")


def test_source_authority_policy_marks_a_share_disclosures_as_primary():
    for record in [
        {
            "source_type": "cninfo_announcement",
            "source_url": "http://static.cninfo.com.cn/finalpage/2026-04-01/report.pdf",
            "title": "贵州茅台2025年年度报告",
        },
        {
            "source_type": "exchange_announcement",
            "source_url": "https://www.sse.com.cn/disclosure/listedinfo/announcement/c/report.pdf",
            "title": "贵州茅台2025年年度报告",
        },
    ]:
        grade = grade_source_authority(record)
        assert grade["authority_level"] == "primary"
        assert "revenue" in grade["allowed_claim_types"]

    eastmoney = grade_source_authority(
        {
            "source_type": "eastmoney_financials",
            "source_url": "https://data.eastmoney.com/bbsj/600519.html",
            "title": "600519 Eastmoney income financial table",
        }
    )
    assert eastmoney["authority_level"] == "market_data"
    assert "revenue" in eastmoney["allowed_claim_types"]


def test_source_authority_policy_limits_market_data_to_market_claims():
    grade = grade_source_authority(
        {
            "source_type": "market_api",
            "source_url": "https://finance.yahoo.com/quote/AMD",
            "title": "AMD market snapshot",
        }
    )

    assert grade["source_authority"] == "market_data"
    assert grade["authority_level"] == "market_data"
    assert "market_price" in grade["allowed_claim_types"]
    assert "revenue" not in grade["allowed_claim_types"]


def test_source_authority_policy_does_not_allow_web_snippet_for_core_financial_claims():
    grade = grade_source_authority(
        {
            "source_type": "web_search",
            "source_url": "https://example.com/amd-news",
            "title": "AMD revenue report",
        }
    )

    assert grade["authority_level"] == "tertiary"
    assert "event" in grade["allowed_claim_types"]
    assert "revenue" not in grade["allowed_claim_types"]


def test_verifier_blocks_core_financial_claim_without_primary_evidence():
    claim = ClaimItem(
        claim_id="cl_revenue",
        section_name="financial_analysis",
        claim_text="AMD revenue was 9.2B in 2025Q4. [web_1]",
        evidence_ids=["web_1"],
        numeric_values={"revenue_billion": 9.2},
        confidence=0.8,
    )
    evidence = [
        {
            "evidence_id": "web_1",
            "source_type": "web_search",
            "source_url": "https://example.com/amd-q4-news",
            "content": "AMD revenue was 9.2B.",
            "metadata": {},
        }
    ]

    result = Verifier().verify(
        claims=[claim],
        markdown="# Executive Summary\n\n## Financial Analysis\n\nAMD revenue was 9.2B in 2025Q4. [web_1]\n\n## Risk Assessment\n",
        evidence_records=evidence,
    )

    assert result["passed"] is False
    assert any("no primary evidence source" in error for error in result["errors"])


def test_verifier_warns_for_period_matched_structured_financial_fallback():
    claim = ClaimItem(
        claim_id="cl_revenue",
        section_name="financial_statements",
        claim_text="NVDA 2026Q1 revenue was 81.615B. [yahoo_quarter]",
        evidence_ids=["yahoo_quarter"],
        numeric_values={"revenue": 81615000000.0},
        confidence=0.8,
        metric_lineage_ids=["lineage_revenue"],
    )
    evidence = [
        {
            "evidence_id": "yahoo_quarter",
            "source_type": "market_api",
            "source_url": "https://finance.yahoo.com/quote/NVDA/financials",
            "content": "Latest income: revenue=81615000000, netIncome=58321000000",
            "metadata": {
                "financials": {
                    "quarterly_income_history": [
                        {"end_date": "2026-04-30", "Total Revenue": 81615000000.0, "Net Income": 58321000000.0}
                    ]
                }
            },
        }
    ]

    result = Verifier().verify(
        claims=[claim],
        markdown="# Executive Summary\n\n## Financial Analysis\n\n## Financial Statements\n\nNVDA 2026Q1 revenue was 81.615B. [yahoo_quarter]\n\n## Risk Assessment\n",
        evidence_records=evidence,
    )

    assert result["passed"] is True
    assert not result["errors"]
    assert any("structured financial data as a fallback" in warning for warning in result["warnings"])


def test_verifier_accepts_core_financial_claim_with_primary_evidence():
    claim = ClaimItem(
        claim_id="cl_revenue",
        section_name="financial_analysis",
        claim_text="AMD revenue was 9.2B in 2025Q4. [filing_1]",
        evidence_ids=["filing_1"],
        numeric_values={"revenue_billion": 9.2},
        confidence=0.8,
    )
    evidence = [
        {
            "evidence_id": "filing_1",
            "source_type": "filing",
            "source_url": "https://www.sec.gov/Archives/edgar/data/amd/10-q.htm",
            "content": "AMD revenue was 9.2B.",
            "metadata": {},
        }
    ]

    result = Verifier().verify(
        claims=[claim],
        markdown="# Executive Summary\n\n## Financial Analysis\n\nAMD revenue was 9.2B in 2025Q4. [filing_1]\n\n## Risk Assessment\n",
        evidence_records=evidence,
    )

    assert result["passed"] is True


def test_verifier_accepts_market_numeric_claim_with_market_data():
    claim = ClaimItem(
        claim_id="cl_price",
        section_name="financial_analysis",
        claim_text="AMD latest close was 424.10 USD. [market_1]",
        evidence_ids=["market_1"],
        numeric_values={"latest_close": 424.10},
        confidence=0.8,
    )
    evidence = [
        {
            "evidence_id": "market_1",
            "source_type": "market_api",
            "source_url": "https://finance.yahoo.com/quote/AMD",
            "content": "AMD latest close 424.10 USD.",
            "metadata": {},
        }
    ]

    result = Verifier().verify(
        claims=[claim],
        markdown="# Executive Summary\n\n## Financial Analysis\n\nAMD latest close was 424.10 USD. [market_1]\n\n## Risk Assessment\n",
        evidence_records=evidence,
    )

    assert result["passed"] is True


def test_verifier_accepts_macro_numeric_claim_with_official_statistics():
    claim = ClaimItem(
        claim_id="cl_cpi",
        section_name="financial_analysis",
        claim_text="CPI was 333.020 in 2026-M04. [bls_1]",
        evidence_ids=["bls_1"],
        numeric_values={"cpi": 333.020},
        confidence=0.8,
    )
    evidence = [
        {
            "evidence_id": "bls_1",
            "source_type": "bls_series",
            "source_url": "https://www.bls.gov/developers/api_signature_v2.htm",
            "content": "CPI latest BLS observation is 333.020 for 2026-M04.",
            "metadata": {},
        }
    ]

    result = Verifier().verify(
        claims=[claim],
        markdown="# Executive Summary\n\n## Financial Analysis\n\nCPI was 333.020 in 2026-M04. [bls_1]\n\n## Risk Assessment\n",
        evidence_records=evidence,
    )

    assert result["passed"] is True
