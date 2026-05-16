import json
from pathlib import Path

from src.data.financial_statement_metrics import build_standard_financial_metrics, build_standard_statement_rows
from src.data.pdf_artifacts import build_pdf_artifacts
from src.agents.deep_analyze_agent import build_rule_claims


def test_eastmoney_three_statement_records_build_standard_metrics():
    records = [
        _eastmoney_record(
            "income",
            {
                "REPORT_DATE": "2025-12-31",
                "NOTICE_DATE": "2026-04-17",
                "TOTAL_OPERATE_INCOME": 172054171890.91,
                "PARENT_NETPROFIT": 82320067101.68,
                "TOTAL_OPERATE_COST": 57370818034.33,
            },
        ),
        _eastmoney_record("balance", {"REPORT_DATE": "2025-12-31", "TOTAL_ASSETS": 300000000000, "TOTAL_LIABILITIES": 80000000000}),
        _eastmoney_record("cashflow", {"REPORT_DATE": "2025-12-31", "NETCASH_OPERATE": 90000000000, "CONSTRUCT_LONG_ASSET_PAY_CASH": 12000000000}),
    ]

    metrics = build_standard_financial_metrics(records)
    rows = build_standard_statement_rows(records)

    names = {item["metric_name"] for item in metrics["metrics"]}
    assert {"revenue", "net_income", "gross_margin", "total_assets", "total_liabilities", "operating_cash_flow", "capex", "free_cash_flow"}.issubset(names)
    assert metrics["metric_count"] >= 8
    assert metrics["coverage"]["has_core_metric_lineage"] is True
    assert {row["statement"] for row in rows} == {"income_statement", "balance_sheet", "cash_flow_statement"}
    assert all(row["source_evidence_id"] for row in rows)


def test_pdf_artifacts_record_failures_without_breaking_pipeline(tmp_path):
    payload = build_pdf_artifacts(
        records=[
            {
                "evidence_id": "pdf_1",
                "source_type": "cninfo_announcement",
                "title": "年度报告",
                "source_url": str(tmp_path / "missing.pdf"),
            }
        ],
        cache_dir=tmp_path / "cache",
    )

    assert payload["pdf_manifest"][0]["status"] == "failed"
    assert payload["pdf_sections"] == []
    assert payload["company_profile_extracted"]["has_profile_hints"] is False


def test_pdf_artifacts_keep_cached_pdf_when_extraction_dependency_missing(monkeypatch, tmp_path):
    pdf_path = tmp_path / "annual_report.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    def fake_extract(**kwargs):
        raise RuntimeError("pymupdf_unavailable")

    monkeypatch.setattr("src.data.pdf_artifacts._extract_sections", fake_extract)

    payload = build_pdf_artifacts(
        records=[
            {
                "evidence_id": "pdf_1",
                "source_type": "exchange_announcement",
                "title": "年度报告",
                "source_url": str(pdf_path),
            }
        ],
        cache_dir=tmp_path / "cache",
    )

    row = payload["pdf_manifest"][0]
    assert row["status"] == "cached"
    assert row["cache_status"] == "cached"
    assert row["extraction_status"] == "failed"
    assert row["extraction_failure_reason"] == "pymupdf_unavailable"
    assert Path(row["file_path"]).exists()


def test_pdf_section_records_become_business_and_governance_claims():
    claims = build_rule_claims(
        records=[
            {
                "evidence_id": "pdf_section_business",
                "source_type": "pdf_section",
                "content": "公司主营业务包括茅台酒销售、系列酒销售和经销商渠道管理。",
                "metadata": {"section_type": "business_overview"},
            },
            {
                "evidence_id": "pdf_section_shareholders",
                "source_type": "pdf_section",
                "content": "股东信息章节披露控股股东及前十大股东持股情况。",
                "metadata": {"section_type": "ownership_governance"},
            },
        ],
        ratio_rows=[],
        trend_rows=[],
    )

    sections = {claim.section_name for claim in claims}
    assert "strategy_business" in sections
    assert "ownership_governance" in sections
    assert any("PDF" in claim.notes for claim in claims)


def test_sec_companyfacts_builds_metric_lineage_rows():
    metrics = build_standard_financial_metrics(
        [
            {
                "evidence_id": "sec_1",
                "symbol": "AMD",
                "period": "2025Q4",
                "source_type": "sec_companyfacts",
                "metadata": {
                    "metrics": {
                        "RevenueFromContractWithCustomerExcludingAssessedTax": {"value": 7438000000, "unit": "USD", "end": "2025-03-29", "filed": "2026-05-06"},
                        "NetIncomeLoss": {"value": 709000000, "unit": "USD", "end": "2025-03-29", "filed": "2026-05-06"},
                        "Assets": {"value": 76926000000, "unit": "USD", "end": "2025-12-27", "filed": "2026-05-06"},
                    }
                },
            }
        ]
    )

    names = {item["metric_name"] for item in metrics["metrics"]}
    assert {"revenue", "net_income", "total_assets"}.issubset(names)
    assert metrics["metric_count"] == 3


def _eastmoney_record(table_type: str, raw: dict) -> dict:
    return {
        "evidence_id": f"ev_{table_type}",
        "sample_id": f"ev_{table_type}",
        "symbol": "600519.SS",
        "period": "2025Q4",
        "source_type": "eastmoney_financials",
        "source_url": "https://data.eastmoney.com/bbsj/600519.html",
        "publish_time": raw.get("NOTICE_DATE", ""),
        "content": json.dumps(raw),
        "metadata": {"provider": "Eastmoney", "table_type": table_type, "raw": raw},
    }
