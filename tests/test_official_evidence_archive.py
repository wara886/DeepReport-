import json

from src.data.official_evidence_archive import archive_official_evidence_manifest, build_official_evidence_artifacts
from src.agents.verifier import Verifier
from src.schemas.claim import ClaimItem


def test_hk_official_evidence_requires_page_anchored_three_statements():
    payload = build_official_evidence_artifacts(
        [
            {
                "evidence_id": "pdf_income",
                "symbol": "0700.HK",
                "period": "FY2024",
                "source_type": "pdf_statement_table",
                "source_url": "https://www1.hkexnews.hk/report.pdf",
                "content": "Revenue 1",
                "metadata": {"page": 10, "provider": "HKEX"},
            }
        ],
        symbol="0700.HK",
        period="FY2024",
        tables=[
            {"table_type": "income_statement", "source_evidence_id": "pdf_income"},
            {"table_type": "balance_sheet", "source_evidence_id": "pdf_income"},
            {"table_type": "cash_flow_statement", "source_evidence_id": "pdf_income"},
        ],
    )

    coverage = payload["evidence_coverage"]
    assert coverage["market"] == "hk"
    assert coverage["has_three_statements"] is True
    assert coverage["pdf_page_anchor_count"] == 1
    assert coverage["draft_generation_allowed"] is True
    assert coverage["formal_delivery_allowed"] is True
    assert coverage["degrade_required"] is False


def test_cn_official_evidence_marks_missing_statements_for_degraded_delivery(tmp_path):
    payload = build_official_evidence_artifacts(
        [],
        symbol="600519.SS",
        period="FY2024",
        tables=[],
    )

    coverage = payload["evidence_coverage"]
    assert coverage["degrade_required"] is True
    assert coverage["draft_generation_allowed"] is True
    assert coverage["formal_delivery_allowed"] is False
    assert "period_matched_official_filing" in coverage["missing_requirements"]
    assert "cash_flow_statement" in coverage["missing_requirements"]
    assert coverage["blocking_reasons"]
    assert coverage["recommended_actions"]
    plan = payload["official_evidence_backfill_plan"]
    assert plan["backfill_required"] is True
    assert any("cninfo_announcements" in task["source_keys"] for task in plan["tasks"])
    assert any(task["task_type"] == "extract_financial_statements" for task in plan["tasks"])

    path = archive_official_evidence_manifest(payload["official_evidence_manifest"], root=tmp_path)
    archived = json.loads(open(path, encoding="utf-8").read())
    assert archived["market"] == "cn_a"


def test_hk_annual_delivery_rejects_mismatched_official_period():
    payload = build_official_evidence_artifacts(
        [
            {
                "evidence_id": "pdf_income",
                "symbol": "0700.HK",
                "period": "FY2023",
                "source_type": "pdf_statement_table",
                "source_url": "https://www1.hkexnews.hk/report.pdf",
                "content": "Revenue 1",
                "metadata": {"page": 10, "provider": "HKEX"},
            }
        ],
        symbol="0700.HK",
        period="FY2024",
        tables=[
            {"table_type": "income_statement", "source_evidence_id": "pdf_income"},
            {"table_type": "balance_sheet", "source_evidence_id": "pdf_income"},
            {"table_type": "cash_flow_statement", "source_evidence_id": "pdf_income"},
        ],
    )

    coverage = payload["evidence_coverage"]
    assert coverage["period_matched_official_record_count"] == 0
    assert coverage["period_mismatched_official_record_count"] == 1
    assert coverage["degrade_required"] is True
    assert coverage["formal_delivery_allowed"] is False
    assert "period_matched_official_filing" in coverage["missing_requirements"]
    plan = payload["official_evidence_backfill_plan"]
    assert plan["backfill_required"] is True
    assert any("hkex_announcements" in task["source_keys"] for task in plan["tasks"])
    assert any("HKEX" in task["query"] for task in plan["tasks"])


def test_cn_annual_delivery_requires_verified_source_period():
    payload = build_official_evidence_artifacts(
        [
            {
                "evidence_id": "annual_pdf_without_period",
                "symbol": "600519.SS",
                "source_type": "cninfo_announcement",
                "source_url": "http://static.cninfo.com.cn/report.pdf",
                "content": "Annual financial statements",
                "metadata": {"page": 1, "provider": "CNINFO"},
            }
        ],
        symbol="600519.SS",
        period="FY2024",
        tables=[
            {"table_type": "income_statement", "source_evidence_id": "annual_pdf_without_period"},
            {"table_type": "balance_sheet", "source_evidence_id": "annual_pdf_without_period"},
            {"table_type": "cash_flow_statement", "source_evidence_id": "annual_pdf_without_period"},
        ],
    )

    coverage = payload["evidence_coverage"]
    manifest_record = payload["official_evidence_manifest"]["records"][0]
    assert manifest_record["period"] == ""
    assert manifest_record["requested_period"] == "FY2024"
    assert coverage["period_unverified_official_record_count"] == 1
    assert coverage["candidate_statement_types"] == ["balance_sheet", "cash_flow_statement", "income_statement"]
    assert coverage["statement_types"] == []
    assert coverage["degrade_required"] is True
    assert coverage["formal_delivery_allowed"] is False


def test_hk_statements_from_non_official_source_do_not_satisfy_delivery_gate():
    payload = build_official_evidence_artifacts(
        [
            {
                "evidence_id": "annual_pdf",
                "symbol": "0700.HK",
                "period": "FY2024",
                "source_type": "hkex_annual_report",
                "source_url": "https://www1.hkexnews.hk/report.pdf",
                "content": "Annual report",
                "metadata": {"page_number": 4, "provider": "HKEX"},
            }
        ],
        symbol="0700.HK",
        period="FY2024",
        tables=[
            {"table_type": "income_statement", "source_evidence_id": "yahoo_tables"},
            {"table_type": "balance_sheet", "source_evidence_id": "yahoo_tables"},
            {"table_type": "cash_flow_statement", "source_evidence_id": "yahoo_tables"},
        ],
    )

    coverage = payload["evidence_coverage"]
    assert coverage["candidate_statement_types"] == ["balance_sheet", "cash_flow_statement", "income_statement"]
    assert coverage["statement_types"] == []
    assert coverage["has_three_statements"] is False
    assert coverage["degrade_required"] is True
    assert coverage["formal_delivery_allowed"] is False


def test_cn_eastmoney_structured_three_statements_satisfy_structured_lineage():
    payload = build_official_evidence_artifacts(
        [
            {
                "evidence_id": "cninfo_q1",
                "symbol": "600519.SS",
                "period": "2026Q1",
                "source_type": "cninfo_announcement",
                "source_url": "http://static.cninfo.com.cn/finalpage/report.pdf",
                "content": "Official quarterly report",
                "metadata": {"page": 1, "provider": "CNINFO"},
            }
        ],
        symbol="600519.SS",
        period="2026Q1",
        tables=[
            {"table_type": "income_statement", "rows": [{"statement": "income_statement", "source_type": "eastmoney_financials"}]},
            {"table_type": "balance_sheet", "rows": [{"statement": "balance_sheet", "source_type": "eastmoney_financials"}]},
            {"table_type": "cash_flow_statement", "rows": [{"statement": "cash_flow_statement", "source_type": "eastmoney_financials"}]},
        ],
    )

    coverage = payload["evidence_coverage"]
    assert coverage["has_three_statements"] is True
    assert coverage["has_official_pdf_three_statements"] is False
    assert coverage["has_structured_three_statements"] is True
    assert coverage["has_formal_delivery_lineage"] is True
    assert coverage["formal_delivery_allowed"] is True
    assert coverage["degrade_required"] is False


def test_us_annual_requires_period_matched_sec_evidence_for_formal_delivery():
    payload = build_official_evidence_artifacts(
        [],
        symbol="AMD",
        period="FY2024",
        tables=[],
    )

    coverage = payload["evidence_coverage"]
    assert coverage["market"] == "us"
    assert coverage["coverage_status"] == "insufficient"
    assert coverage["draft_generation_allowed"] is True
    assert coverage["formal_delivery_allowed"] is False
    assert coverage["degrade_required"] is True
    assert "period_matched_official_filing" in coverage["missing_requirements"]
    assert any("SEC" in action for action in coverage["recommended_actions"])


def test_us_annual_period_matched_sec_evidence_allows_formal_delivery():
    payload = build_official_evidence_artifacts(
        [
            {
                "evidence_id": "sec_10k",
                "symbol": "AMD",
                "period": "FY2024",
                "source_type": "sec_filing",
                "source_url": "https://www.sec.gov/Archives/edgar/data/0000002488/10-k.htm",
                "content": "Form 10-K fiscal year 2024.",
            }
        ],
        symbol="AMD",
        period="FY2024",
        tables=[],
    )

    coverage = payload["evidence_coverage"]
    assert coverage["coverage_status"] == "sufficient"
    assert coverage["formal_delivery_allowed"] is True
    assert coverage["degrade_required"] is False
    assert coverage["period_matched_official_record_count"] == 1


def test_archive_persists_official_source_text_snapshot(tmp_path):
    source_record = {
        "evidence_id": "hkex_report",
        "symbol": "0700.HK",
        "period": "FY2024",
        "source_type": "hkex_annual_report",
        "source_url": "https://www1.hkexnews.hk/report.pdf",
        "content": "[PDF page 4] Revenue disclosure.",
        "metadata": {"page_number": 4},
    }
    manifest = build_official_evidence_artifacts(
        [source_record],
        symbol="0700.HK",
        period="FY2024",
        tables=[],
    )["official_evidence_manifest"]

    path = archive_official_evidence_manifest(manifest, root=tmp_path, source_records=[source_record])
    archived_manifest = json.loads(open(path, encoding="utf-8").read())
    archived_records_path = archived_manifest["archived_records_path"]

    assert archived_manifest["archive_version"]
    assert archived_records_path
    archived_record = json.loads(open(archived_records_path, encoding="utf-8").readline())
    assert archived_record["content"] == "[PDF page 4] Revenue disclosure."


def test_financial_pdf_claim_without_page_anchor_is_rejected():
    report = Verifier().verify(
        claims=[
            ClaimItem(
                claim_id="cl_fin",
                section_name="financial_analysis",
                claim_text="Revenue was 100. [pdf_fin]",
                evidence_ids=["pdf_fin"],
                numeric_values={"revenue": 100.0},
                confidence=0.9,
            )
        ],
        markdown="## Executive Summary\n## Financial Analysis\nRevenue was 100. [pdf_fin]\n## Risk Assessment",
        evidence_records=[
            {
                "evidence_id": "pdf_fin",
                "source_type": "pdf_statement_table",
                "source_url": "https://www1.hkexnews.hk/report.pdf",
                "content": "Revenue was 100.",
                "metadata": {"provider": "HKEX"},
            }
        ],
    )

    assert any("without a page anchor" in error for error in report["errors"])


def test_governance_pdf_claim_requires_page_anchor_and_accepts_page_number():
    claim = ClaimItem(
        claim_id="cl_governance",
        section_name="ownership_governance",
        claim_text="The annual report discloses the board structure. [pdf_governance]",
        evidence_ids=["pdf_governance"],
        confidence=0.8,
    )
    markdown = (
        "## Executive Summary\n## Financial Analysis\n## Risk Assessment\n"
        "## Ownership and Governance\n"
        "The annual report discloses the board structure. [pdf_governance]"
    )
    record = {
        "evidence_id": "pdf_governance",
        "source_type": "pdf_section",
        "source_url": "https://www1.hkexnews.hk/report.pdf",
        "content": "Board structure",
        "metadata": {"provider": "HKEX"},
    }

    rejected = Verifier().verify(claims=[claim], markdown=markdown, evidence_records=[record])
    assert any("without a page anchor" in error for error in rejected["errors"])

    record["metadata"]["page_number"] = 18
    accepted = Verifier().verify(claims=[claim], markdown=markdown, evidence_records=[record])
    assert not any("without a page anchor" in error for error in accepted["errors"])
