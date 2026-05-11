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
