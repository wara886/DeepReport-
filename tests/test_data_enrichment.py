import json
from pathlib import Path
import sys

from src.data.financial_statement_metrics import build_standard_financial_metrics, build_standard_statement_rows
from src.data import yahoo_finance as yahoo_finance_module
from src.data.yahoo_finance import yahoo_financials_to_evidence
from src.utils.periods import period_match
from src.data.pdf_artifacts import build_pdf_artifacts, _extract_pdfplumber_statement_tables
from src.agents.multi_agent_orchestrator import _pdf_tables_as_evidence_records
from src.agents.deep_analyze_agent import apply_evidence_gate, build_rule_claims, _infer_company_analysis_profile


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


def test_company_profile_inference_does_not_misclassify_moutai_as_semiconductor():
    profile = _infer_company_analysis_profile(
        "600519.SS",
        [
            {
                "title": "Kweichow Moutai annual report",
                "content": "The main business of the Company is the production and sales of Moutai liquor and series liquor.",
            },
            {"title": "Market note", "content": "AI appears in an unrelated market paragraph."},
        ],
        [],
    )

    assert profile["category"] == "consumer"
    assert "白酒" in profile["label"]


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
        expected_period="2025Q4",
    )

    sections = {claim.section_name for claim in claims}
    assert "strategy_business" in sections
    assert "ownership_governance" in sections
    assert any("PDF" in claim.notes for claim in claims)


def test_pdf_sections_generate_generic_business_governance_and_risk_claims():
    claims = build_rule_claims(
        records=[
            {
                "evidence_id": "pdf_sales",
                "source_type": "pdf_section",
                "content": "贵州茅台2026 年第一季度报告 销售情况 茅台酒 系列酒 直销 批发代理 国内 国外 i 茅台 数字营销平台 经销商情况 国内 2098 国外 124。",
                "metadata": {"section_type": "business_overview"},
            },
            {
                "evidence_id": "pdf_shareholder",
                "source_type": "pdf_section",
                "content": "前10名股东 中国贵州茅台酒厂（集团）有限责任公司 香港中央结算有限公司 贵州省国有资本运营有限责任公司。",
                "metadata": {"section_type": "ownership_governance"},
            },
            {
                "evidence_id": "pdf_risk",
                "source_type": "pdf_section",
                "content": "重大风险提示 本公司未来发展存在不确定性，敬请投资者注意投资风险。",
                "metadata": {"section_type": "risk_factors"},
            },
        ],
        ratio_rows=[],
        trend_rows=[],
        expected_period="2026Q1",
    )
    text = "\n".join(claim.claim_text for claim in claims)

    assert "PDF" in text
    assert "提供了以下" in text
    assert "股权与治理" in text or "风险因素" in text

def test_pdf_section_claims_from_future_quarter_are_rejected_for_annual_report():
    claims = build_rule_claims(
        records=[
            {
                "evidence_id": "pdf_q1_business",
                "source_type": "pdf_section",
                "period": "2026Q1",
                "content": "贵州茅台酒股份有限公司2026 年第一季度报告，主营业务收入和经销商情况。",
                "metadata": {"section_type": "business_overview"},
            },
            {
                "evidence_id": "pdf_annual_business",
                "source_type": "pdf_section",
                "content": "贵州茅台酒股份有限公司2025 年年度报告，主营业务和渠道结构。",
                "metadata": {"section_type": "business_overview"},
            },
        ],
        ratio_rows=[],
        trend_rows=[],
        expected_period="2025Q4",
    )

    accepted, gate = apply_evidence_gate(
        claims=claims,
        evidence_records=[
            {
                "evidence_id": "pdf_q1_business",
                "source_type": "pdf_section",
                "period": "2026Q1",
                "content": "贵州茅台酒股份有限公司2026 年第一季度报告，主营业务收入和经销商情况。",
            },
            {
                "evidence_id": "pdf_annual_business",
                "source_type": "pdf_section",
                "content": "贵州茅台酒股份有限公司2025 年年度报告，主营业务和渠道结构。",
            },
        ],
        expected_period="2025Q4",
    )

    assert gate["rejected_claim_count"] == 0
    assert all("2026 年第一季度报告" not in claim.claim_text for claim in accepted)
    assert any("2025 年年度报告" in claim.claim_text for claim in accepted)


def test_rule_claims_backfill_generic_tech_peer_valuation_risk_and_conclusion():
    claims = build_rule_claims(
        records=[
            {
                "evidence_id": "sec_amd",
                "symbol": "AMD",
                "period": "2025Q1",
                "source_type": "sec_companyfacts",
                "content": "SEC companyfacts for AMD.",
                "metadata": {"metrics": {"Revenues": {"value": 1000000000, "unit": "USD", "end": "2025-12-27"}}},
            }
        ],
        ratio_rows=[],
        trend_rows=[],
    )
    sections = {claim.section_name for claim in claims}
    text = "\n".join(claim.claim_text for claim in claims)

    assert {"strategy_business", "ownership_governance", "peer_compare", "valuation", "valuation_sensitivity", "risks", "conclusion"}.issubset(sections)
    assert "AMD" in text
    assert "P/E" in text or "P/B" in text or "P/S" in text
    assert "peer_compare" in sections
    assert "conclusion" in sections


def test_sec_companyfacts_rejects_annual_10k_for_q1():
    record = {
        "evidence_id": "sec_nvda",
        "symbol": "NVDA",
        "period": "2026Q1",
        "source_type": "sec_companyfacts",
        "metadata": {
            "metrics": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {
                    "value": 26914000000,
                    "unit": "USD",
                    "end": "2022-01-30",
                    "filed": "2022-03-18",
                    "form": "10-K",
                    "frame": "CY2021",
                },
                "Revenues": {
                    "value": 215938000000,
                    "unit": "USD",
                    "end": "2026-01-25",
                    "filed": "2026-02-25",
                    "form": "10-K",
                    "frame": "CY2025",
                },
                "NetIncomeLoss": {"value": 120067000000, "unit": "USD", "end": "2026-01-25", "filed": "2026-02-25", "form": "10-K"},
                "Assets": {"value": 206803000000, "unit": "USD", "end": "2026-01-25", "filed": "2026-02-25", "form": "10-K"},
                "CashAndCashEquivalentsAtCarryingValue": {"value": 10605000000, "unit": "USD", "end": "2026-01-25", "filed": "2026-02-25", "form": "10-K"},
                "NetCashProvidedByUsedInOperatingActivities": {"value": 102718000000, "unit": "USD", "end": "2026-01-25", "filed": "2026-02-25", "form": "10-K"},
                "PaymentsToAcquirePropertyPlantAndEquipment": {
                    "value": 372000000,
                    "unit": "USD",
                    "end": "2020-07-26",
                    "filed": "2020-08-19",
                    "form": "10-Q",
                },
                "PaymentsToAcquireProductiveAssets": {
                    "value": 6042000000,
                    "unit": "USD",
                    "end": "2026-01-25",
                    "filed": "2026-02-25",
                    "form": "10-K",
                },
            }
        },
    }

    metrics = build_standard_financial_metrics([record])
    rows = build_standard_statement_rows([record])

    assert metrics["metric_count"] == 0
    assert metrics["rejected_metric_count"] >= 7
    assert rows == []


def test_period_match_does_not_accept_all_january_rows_as_q1():
    assert period_match("2026Q1", report_date="2026-01-15", raw={"form": "10-Q"}) is False
    assert period_match("2026Q1", report_date="2026-01-15", raw={"fy": "2026", "fp": "Q1"}) is True


def test_yahoo_market_snapshot_labels_historical_context(monkeypatch):
    monkeypatch.setattr(
        yahoo_finance_module,
        "fetch_yahoo_chart_snapshot",
        lambda **kwargs: {
            "symbol": kwargs["symbol"],
            "last_close": 100.0,
            "previous_close": 98.0,
            "change_pct": 2.0,
            "latest_volume": 123,
            "latest_date": "2026-05-22",
            "currency": "USD",
            "source_url": "https://finance.yahoo.com/quote/TSLA",
        },
    )

    evidence = yahoo_finance_module.yahoo_snapshot_to_evidence("TSLA", period="2025Q3")

    assert evidence["metadata"]["context_type"] == "current_market_snapshot"
    assert evidence["metadata"]["historical_report_context"] is True
    assert "not target-period statement evidence" in evidence["content"]


def test_market_api_quarterly_financials_build_statement_rows_for_quarter():
    record = {
        "evidence_id": "nvda_yahoo",
        "symbol": "NVDA",
        "period": "2026Q1",
        "source_type": "market_api",
        "metadata": {
            "financials": {
                "income_history": [{"end_date": "2026-01-31", "Total Revenue": 215938000000.0, "Net Income": 120067000000.0}],
                "quarterly_income_history": [{"end_date": "2026-04-30", "Total Revenue": 81615000000.0, "Net Income": 58321000000.0, "Gross Profit": 60815000000.0}],
                "quarterly_balance_history": [{"end_date": "2026-04-30", "Total Assets": 259474000000.0, "Total Liabilities Net Minority Interest": 60000000000.0, "Stockholders Equity": 199474000000.0}],
                "quarterly_cashflow_history": [{"end_date": "2026-04-30", "Operating Cash Flow": 50344000000.0, "Capital Expenditure": -1757000000.0, "Free Cash Flow": 48587000000.0}],
            }
        },
    }

    metrics = build_standard_financial_metrics([record])
    rows = build_standard_statement_rows([record])
    by_metric = {item["metric_name"]: item for item in metrics["metrics"]}

    assert by_metric["revenue"]["value"] == 81615000000.0
    assert by_metric["net_income"]["value"] == 58321000000.0
    assert by_metric["capex"]["value"] == 1757000000.0
    assert by_metric["gross_margin"]["period_match"] is True
    assert {row["statement"] for row in rows} == {"income_statement", "balance_sheet", "cash_flow_statement"}
    assert any(row["line_item"] == "free_cash_flow" and row["value"] == 48587000000.0 for row in rows)


def test_market_api_historical_quarter_selects_target_row_not_latest():
    record = {
        "evidence_id": "tsla_yahoo",
        "symbol": "TSLA",
        "period": "2025Q3",
        "source_type": "market_api",
        "metadata": {
            "financials": {
                "quarterly_income_history": [
                    {"end_date": "2026-03-31", "Total Revenue": 24000000000.0, "Net Income": 1000000000.0},
                    {"end_date": "2025-09-30", "Total Revenue": 28100000000.0, "Net Income": 1370000000.0, "Gross Profit": 5100000000.0},
                ],
                "quarterly_balance_history": [
                    {"end_date": "2026-03-31", "Total Assets": 130000000000.0, "Total Liabilities Net Minority Interest": 52000000000.0},
                    {"end_date": "2025-09-30", "Total Assets": 122000000000.0, "Total Liabilities Net Minority Interest": 49000000000.0},
                ],
                "quarterly_cashflow_history": [
                    {"end_date": "2026-03-31", "Operating Cash Flow": 800000000.0, "Capital Expenditure": -3000000000.0, "Free Cash Flow": -2200000000.0},
                    {"end_date": "2025-09-30", "Operating Cash Flow": 6800000000.0, "Capital Expenditure": -2500000000.0, "Free Cash Flow": 4300000000.0},
                ],
            }
        },
    }

    metrics = build_standard_financial_metrics([record])
    rows = build_standard_statement_rows([record])
    by_metric = {item["metric_name"]: item for item in metrics["metrics"]}

    assert by_metric["revenue"]["value"] == 28100000000.0
    assert by_metric["net_income"]["value"] == 1370000000.0
    assert by_metric["free_cash_flow"]["value"] == 4300000000.0
    assert {row["report_date"] for row in rows} == {"2025-09-30"}
    assert all(row["period_match"] is True for row in rows)


def test_yahoo_financials_evidence_describes_target_quarter_not_latest(monkeypatch):
    def fake_financials(symbol):
        return {
            "quarterly_income_history": [
                {"end_date": "2026-03-31", "Total Revenue": 24000000000.0, "Net Income": 1000000000.0},
                {"end_date": "2025-09-30", "Total Revenue": 28100000000.0, "Net Income": 1370000000.0, "Gross Profit": 5100000000.0},
            ],
            "quarterly_balance_history": [
                {"end_date": "2026-03-31", "Total Assets": 130000000000.0, "Total Liabilities Net Minority Interest": 52000000000.0},
                {"end_date": "2025-09-30", "Total Assets": 122000000000.0, "Total Liabilities Net Minority Interest": 49000000000.0},
            ],
            "quarterly_cashflow_history": [
                {"end_date": "2026-03-31", "Operating Cash Flow": 800000000.0, "Capital Expenditure": -3000000000.0, "Free Cash Flow": -2200000000.0},
                {"end_date": "2025-09-30", "Operating Cash Flow": 6800000000.0, "Capital Expenditure": -2500000000.0, "Free Cash Flow": 4300000000.0},
            ],
        }

    monkeypatch.setattr("src.data.yahoo_finance.fetch_yahoo_financials", fake_financials)

    evidence = yahoo_financials_to_evidence("TSLA", "2025Q3")

    assert evidence is not None
    assert "2025Q3 income: end_date=2025-09-30" in evidence["content"]
    assert "revenue=28100000000.0" in evidence["content"]
    assert "revenue=24000000000.0" not in evidence["content"]


def test_quarterly_statement_claims_use_only_period_matched_statement_evidence():
    records = [
        {
            "evidence_id": "sec_annual",
            "symbol": "NVDA",
            "period": "2026Q1",
            "source_type": "sec_companyfacts",
            "metadata": {
                "metrics": {
                    "Revenues": {"value": 215938000000, "unit": "USD", "end": "2026-01-25", "form": "10-K"},
                    "NetIncomeLoss": {"value": 120067000000, "unit": "USD", "end": "2026-01-25", "form": "10-K"},
                }
            },
        },
        {
            "evidence_id": "yahoo_quarter",
            "symbol": "NVDA",
            "period": "2026Q1",
            "source_type": "market_api",
            "metadata": {
                "financials": {
                    "quarterly_income_history": [{"end_date": "2026-04-30", "Total Revenue": 81615000000.0, "Net Income": 58321000000.0}],
                    "quarterly_balance_history": [{"end_date": "2026-04-30", "Total Assets": 259474000000.0, "Total Liabilities Net Minority Interest": 64000000000.0}],
                    "quarterly_cashflow_history": [{"end_date": "2026-04-30", "Operating Cash Flow": 50344000000.0, "Capital Expenditure": -1757000000.0, "Free Cash Flow": 48587000000.0}],
                }
            },
        },
    ]
    statement_view = {"rows": build_standard_statement_rows(records), "coverage": {"has_three_statement_view": True, "line_item_count": 8}}
    claims = build_rule_claims(records, [], [], statement_view=statement_view, expected_period="2026Q1")
    period_sensitive = [claim for claim in claims if claim.section_name in {"financial_statements", "valuation", "valuation_sensitivity", "executive_summary"}]

    assert period_sensitive
    assert all("sec_annual" not in claim.evidence_ids for claim in period_sensitive)
    assert any("yahoo_quarter" in claim.evidence_ids for claim in period_sensitive)
    assert any(claim.section_name == "financial_analysis" and "yahoo_quarter" in claim.evidence_ids for claim in claims)


def test_historical_quarter_claim_text_uses_requested_period_not_latest_label():
    records = [
        {
            "evidence_id": "tsla_sec",
            "symbol": "TSLA",
            "period": "2025Q3",
            "source_type": "sec_companyfacts",
            "metadata": {
                "metrics": {
                    "Revenues": {"value": 69926000000, "unit": "USD", "end": "2025-09-30", "filed": "2025-10-23", "form": "10-Q"},
                    "NetIncomeLoss": {"value": 2954000000, "unit": "USD", "end": "2025-09-30", "filed": "2025-10-23", "form": "10-Q"},
                    "NetCashProvidedByUsedInOperatingActivities": {"value": 10934000000, "unit": "USD", "end": "2025-09-30", "filed": "2025-10-23", "form": "10-Q"},
                    "PaymentsToAcquireProductiveAssets": {"value": 6134000000, "unit": "USD", "end": "2025-09-30", "filed": "2025-10-23", "form": "10-Q"},
                }
            },
        }
    ]
    statement_view = {"rows": build_standard_statement_rows(records), "coverage": {"has_three_statement_view": True, "line_item_count": 4}}

    claims = build_rule_claims(records, [], [], statement_view=statement_view, expected_period="2025Q3")
    text = "\n".join(claim.claim_text for claim in claims)

    assert "2025Q3 财务分析显示" in text
    assert "基于 2025Q3" in text or "2026Q1" not in text
    assert "2026Q1" not in text


def test_sec_companyfacts_latest_synonym_for_annual_q4():
    record = {
        "evidence_id": "sec_nvda",
        "symbol": "NVDA",
        "period": "2025Q4",
        "source_type": "sec_companyfacts",
        "metadata": {
            "metrics": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": {"value": 26914000000, "unit": "USD", "end": "2022-01-30", "filed": "2022-03-18", "form": "10-K"},
                "Revenues": {"value": 215938000000, "unit": "USD", "end": "2026-01-25", "filed": "2026-02-25", "form": "10-K"},
                "NetIncomeLoss": {"value": 120067000000, "unit": "USD", "end": "2026-01-25", "filed": "2026-02-25", "form": "10-K"},
                "Assets": {"value": 206803000000, "unit": "USD", "end": "2026-01-25", "filed": "2026-02-25", "form": "10-K"},
                "CashAndCashEquivalentsAtCarryingValue": {"value": 10605000000, "unit": "USD", "end": "2026-01-25", "filed": "2026-02-25", "form": "10-K"},
                "NetCashProvidedByUsedInOperatingActivities": {"value": 102718000000, "unit": "USD", "end": "2026-01-25", "filed": "2026-02-25", "form": "10-K"},
                "PaymentsToAcquirePropertyPlantAndEquipment": {"value": 372000000, "unit": "USD", "end": "2020-07-26", "filed": "2020-08-19", "form": "10-Q"},
                "PaymentsToAcquireProductiveAssets": {"value": 6042000000, "unit": "USD", "end": "2026-01-25", "filed": "2026-02-25", "form": "10-K"},
            }
        },
    }

    metrics = build_standard_financial_metrics([record])
    by_metric = {item["metric_name"]: item for item in metrics["metrics"]}

    assert metrics["metric_count"] >= 7
    assert by_metric["revenue"]["value"] == 215938000000
    assert by_metric["capex"]["value"] == 6042000000
    assert by_metric["free_cash_flow"]["value"] == 96676000000

def test_macro_evidence_without_symbol_does_not_become_company_business_overview():
    claims = build_rule_claims(
        records=[
            {
                "evidence_id": "bls_cpi",
                "source_type": "bls_series",
                "content": "Consumer Price Index latest observation.",
            },
            {
                "evidence_id": "sec_amd",
                "symbol": "AMD",
                "period": "2026Q1",
                "source_type": "sec_companyfacts",
                "content": "SEC companyfacts for AMD.",
                "metadata": {"metrics": {"RevenueFromContractWithCustomerExcludingAssessedTax": {"value": 7438000000, "unit": "USD"}}},
            },
        ],
        ratio_rows=[],
        trend_rows=[
            {"symbol": "Company", "evidence_count": 1, "unique_sources": 1, "sample_ids": "bls_cpi"},
            {"symbol": "AMD", "evidence_count": 1, "unique_sources": 1, "sample_ids": "sec_amd"},
        ],
    )
    text = "\n".join(claim.claim_text for claim in claims)

    assert "Company 的证据覆盖" not in text
    assert "AMD 的证据覆盖" in text


def test_minimum_valuation_claims_compute_multiples_and_sensitivity():
    claims = build_rule_claims(
        records=[
            {
                "evidence_id": "sec_amd",
                "symbol": "AMD",
                "period": "2026Q1",
                "source_type": "sec_companyfacts",
                "content": "SEC companyfacts for AMD.",
                "metadata": {"metrics": {"RevenueFromContractWithCustomerExcludingAssessedTax": {"value": 10_000_000_000, "unit": "USD"}}},
            },
            {
                "evidence_id": "market_amd",
                "symbol": "AMD",
                "period": "2026Q1",
                "source_type": "market_api",
                "content": "AMD market snapshot.",
                "metadata": {"snapshot": {"market_cap_billion": 100.0}},
            },
        ],
        ratio_rows=[],
        trend_rows=[],
        statement_view={
            "rows": [
                {"symbol": "AMD", "period": "2026Q1", "statement": "income_statement", "line_item": "revenue", "value": 10_000_000_000.0},
                {"symbol": "AMD", "period": "2026Q1", "statement": "income_statement", "line_item": "net_income", "value": 1_000_000_000.0},
                {"symbol": "AMD", "period": "2026Q1", "statement": "balance_sheet", "line_item": "total_equity", "value": 25_000_000_000.0},
            ]
        },
    )
    text = "\n".join(claim.claim_text for claim in claims)

    assert "P/E 约为 100.0x" in text
    assert "P/B 约为 4.0x" in text
    assert "P/S 约为 10.0x" in text
    assert "敏感性分析显示" in text


def test_eastmoney_claims_use_professional_units_not_scientific_notation():
    claims = build_rule_claims(
        records=[
            _eastmoney_record(
                "income",
                {
                    "REPORT_DATE": "2025-12-31",
                    "TOTAL_OPERATE_INCOME": 172054171890.91,
                    "PARENT_NETPROFIT": 82320067101.68,
                },
            )
        ],
        ratio_rows=[],
        trend_rows=[],
    )
    text = "\n".join(claim.claim_text for claim in claims)

    assert "亿元" in text
    assert "e+" not in text.lower()


def test_sec_companyfacts_builds_metric_lineage_rows():
    metrics = build_standard_financial_metrics(
        [
            {
                "evidence_id": "sec_1",
                "symbol": "AMD",
                "period": "2025Q1",
                "source_type": "sec_companyfacts",
                "metadata": {
                    "metrics": {
                        "RevenueFromContractWithCustomerExcludingAssessedTax": {"value": 7438000000, "unit": "USD", "end": "2025-03-29", "filed": "2026-05-06"},
                        "NetIncomeLoss": {"value": 709000000, "unit": "USD", "end": "2025-03-29", "filed": "2026-05-06"},
                        "Assets": {"value": 76926000000, "unit": "USD", "end": "2025-03-29", "filed": "2026-05-06"},
                        "NetCashProvidedByUsedInOperatingActivities": {"value": 1200000000, "unit": "USD", "end": "2025-03-29", "filed": "2026-05-06"},
                        "PaymentsToAcquirePropertyPlantAndEquipment": {"value": 200000000, "unit": "USD", "end": "2025-03-29", "filed": "2026-05-06"},
                    }
                },
            }
        ]
    )

    names = {item["metric_name"] for item in metrics["metrics"]}
    assert {"revenue", "net_income", "total_assets", "operating_cash_flow", "capex", "free_cash_flow"}.issubset(names)
    assert metrics["metric_count"] == 6


def test_sec_companyfacts_builds_cash_flow_statement_rows():
    rows = build_standard_statement_rows(
        [
            {
                "evidence_id": "sec_1",
                "symbol": "AAPL",
                "period": "2026Q1",
                "source_type": "sec_companyfacts",
                "metadata": {
                    "metrics": {
                        "NetCashProvidedByUsedInOperatingActivities": {"value": 33000000000, "unit": "USD", "end": "2026-03-28", "filed": "2026-05-01"},
                        "PaymentsToAcquirePropertyPlantAndEquipment": {"value": 3000000000, "unit": "USD", "end": "2026-03-28", "filed": "2026-05-01"},
                    }
                },
            }
        ]
    )

    cash_rows = [row for row in rows if row["statement"] == "cash_flow_statement"]
    values = {row["line_item"]: row["value"] for row in cash_rows}
    assert values["operating_cash_flow"] == 33000000000
    assert values["capex"] == 3000000000
    assert values["free_cash_flow"] == 30000000000


def test_pdf_statement_table_record_builds_standard_metrics_and_rows():
    records = [
        {
            "evidence_id": "pdf_table_1",
            "symbol": "TSLA",
            "period": "2026Q1",
            "source_type": "pdf_statement_table",
            "metadata": {
                "table_id": "tbl_pdf_income",
                "table_type": "income_statement",
                "currency": "USD",
                "unit": "millions",
                "rows": [
                    {"line_item": "revenue", "value": 22390.0},
                    {"line_item": "gross_profit", "value": 4250.0},
                    {"line_item": "net_income", "value": 477.0},
                ],
            },
        }
    ]

    metrics = build_standard_financial_metrics(records)
    rows = build_standard_statement_rows(records)

    names = {item["metric_name"] for item in metrics["metrics"]}
    assert {"revenue", "gross_profit", "gross_margin", "net_income"}.issubset(names)
    assert all(item["source_table_id"] == "tbl_pdf_income" for item in metrics["metrics"])
    assert rows[0]["source_type"] == "pdf_statement_table"
    assert rows[0]["unit"] == "USD_million"


def test_pdf_tables_artifacts_become_statement_table_evidence_records():
    records = _pdf_tables_as_evidence_records(
        [
            {
                "table_id": "pdf_tbl_income",
                "table_type": "income_statement",
                "source_url": "https://example.com/q1.pdf",
                "page": 24,
                "rows": [{"line_item": "revenue", "value": 22390.0}],
                "unit": "millions",
                "currency": "USD",
                "evidence_id": "pdf_source",
                "extraction_method": "pymupdf_find_tables_statement_heuristic_v1",
            }
        ],
        symbol="TSLA",
        period="2026Q1",
    )

    assert records[0]["source_type"] == "pdf_statement_table"
    assert records[0]["metadata"]["table_type"] == "income_statement"
    assert "revenue=22390.0" in records[0]["content"]


def test_pdfplumber_statement_table_extractor_normalizes_income_table(monkeypatch, tmp_path):
    class FakePage:
        def extract_text(self):
            return "Consolidated Statements of Operations in millions total revenues gross profit net income"

        def extract_tables(self, table_settings=None):
            return [
                [
                    ["", "Three Months Ended"],
                    ["Total revenues", "22,390"],
                    ["Gross profit", "4,250"],
                    ["Net income", "477"],
                ]
            ]

    class FakePdf:
        pages = [FakePage()]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakePdfPlumber:
        @staticmethod
        def open(path):
            return FakePdf()

    monkeypatch.setitem(sys.modules, "pdfplumber", FakePdfPlumber)
    pdf_path = tmp_path / "fake.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    tables = _extract_pdfplumber_statement_tables(pdf_path, "ev_pdf", "https://example.com/q1.pdf", max_pages=1)

    assert tables
    assert tables[0]["extraction_method"] == "pdfplumber_extract_tables_statement_heuristic_v1"
    assert tables[0]["table_type"] == "income_statement"
    assert {row["line_item"] for row in tables[0]["rows"]} >= {"revenue", "gross_profit", "net_income"}


def test_statement_rows_generate_three_statement_summary_claims_with_cashflow_gap():
    claims = build_rule_claims(
        records=[
            {
                "evidence_id": "sec_amd",
                "symbol": "AMD",
                "period": "2026Q1",
                "source_type": "sec_companyfacts",
                "content": "SEC companyfacts for AMD.",
                "metadata": {
                    "metrics": {
                        "RevenueFromContractWithCustomerExcludingAssessedTax": {"value": 7438000000, "unit": "USD", "end": "2025-03-29"},
                        "NetIncomeLoss": {"value": 709000000, "unit": "USD", "end": "2025-03-29"},
                        "Assets": {"value": 76926000000, "unit": "USD", "end": "2025-12-27"},
                        "CashAndCashEquivalentsAtCarryingValue": {"value": 5539000000, "unit": "USD", "end": "2025-12-27"},
                    }
                },
            }
        ],
        ratio_rows=[],
        trend_rows=[],
        statement_view={
            "rows": [
                {"symbol": "AMD", "period": "2026Q1", "statement": "income_statement", "line_item": "revenue", "value": 7438000000.0},
                {"symbol": "AMD", "period": "2026Q1", "statement": "income_statement", "line_item": "net_income", "value": 709000000.0},
                {"symbol": "AMD", "period": "2026Q1", "statement": "balance_sheet", "line_item": "total_assets", "value": 76926000000.0},
                {"symbol": "AMD", "period": "2026Q1", "statement": "balance_sheet", "line_item": "cash_and_equivalents", "value": 5539000000.0},
            ]
        },
    )
    text = "\n".join(claim.claim_text for claim in claims if claim.section_name == "financial_statements")

    assert "利润表摘要" in text
    assert "资产负债表摘要" in text
    assert "现金流量表缺口" in text


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
