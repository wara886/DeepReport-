import json
from pathlib import Path

import pandas as pd
import pytest

from src.agents.deep_analyze_agent import _attach_metric_lineage_to_claims, apply_evidence_gate
from src.agents.research_blackboard import (
    apply_pre_write_critic,
    initialize_research_blackboard,
    quality_generalization_checks,
    update_blackboard_for_task,
)
from src.data.company_universe import resolve_company_identifier_with_diagnostics, resolve_symbol
from src.data.financial_statement_metrics import build_standard_financial_metrics
from src.evaluation.valuation_audit import audit_valuation_model
from src.evaluation.company_report_scorecard import build_company_report_scorecard
from src.schemas.claim import ClaimItem
from src.features.company_valuation import _yahoo_ratio_to_pct, build_peer_comparison, perform_company_valuation
from src.features.financial_metric_lineage import build_financial_metric_lineage, build_financial_metric_tables
from src.features.financial_ratios import build_financial_ratios
from src.features.financial_statements import build_three_statement_view
from src.features.peer_compare import build_peer_compare
from src.features.risk_signals import build_risk_signals
from src.features.trend_analysis import build_trend_features
from src.search.search_manager import _record_matches_requested_company


def _sample_manifest_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "sample_id": "s1",
                "source_type": "financials",
                "symbol": "AAPL",
                "period": "2025Q4",
                "title": "AAPL 10-Q summary",
                "publish_time": "2026-01-30T00:00:00Z",
                "content": "Revenue 126.3B, gross margin 46.8%.",
                "source_url": "https://example.com/aapl",
                "trust_level": "high",
            },
            {
                "sample_id": "s2",
                "source_type": "news",
                "symbol": "MSFT",
                "period": "2025Q4",
                "title": "MSFT update",
                "publish_time": "2026-02-01T00:00:00Z",
                "content": "Demand stable but volatility remains a risk.",
                "source_url": "https://example.com/msft",
                "trust_level": "medium",
            },
        ]
    )


def test_financial_ratios_extracts_numeric_fields():
    df = build_financial_ratios(_sample_manifest_df())
    row = df[df["symbol"] == "AAPL"].iloc[0]
    assert float(row["revenue_billion"]) == 126.3
    assert float(row["gross_margin_pct"]) == 46.8


def test_trend_and_peer_features_shape():
    manifest = _sample_manifest_df()
    trend = build_trend_features(manifest)
    peer = build_peer_compare(manifest)
    assert set(trend.columns) >= {"symbol", "period", "evidence_count"}
    assert set(peer.columns) >= {"symbol", "peer_rank", "avg_trust_weight"}


def test_trend_features_tolerate_records_without_manifest_columns():
    trend = build_trend_features(pd.DataFrame([{"evidence_id": "ev_1", "content": "unstructured note"}]))

    assert trend.iloc[0]["evidence_count"] == 1
    assert trend.iloc[0]["sample_ids"] == "ev_1"


def test_risk_signals_contains_level():
    risk = build_risk_signals(_sample_manifest_df())
    assert set(risk["risk_level"]).issubset({"low", "medium", "high"})


def test_company_symbol_resolver_handles_company_name():
    assert resolve_symbol("NVIDIA Corporation", raw_data_root="data/raw/real_data") == "NVDA"


def test_company_symbol_resolver_handles_mixed_case_ticker_in_chinese_query():
    resolution = resolve_company_identifier_with_diagnostics(
        "分析 Nvda 2025Q4 财务表现",
        raw_data_root="data/raw/real_data",
    )

    assert resolution["resolved"] is True
    assert resolution["symbol"] == "NVDA"
    assert resolution["match_type"] == "symbol_token"


def test_company_symbol_resolver_uses_builtin_fallback_catalog_for_remote_only_ticker():
    resolution = resolve_company_identifier_with_diagnostics(
        "AMD",
        raw_data_root="data/raw/real_data",
    )

    assert resolution["resolved"] is True
    assert resolution["symbol"] == "AMD"
    assert resolution["company_name"] == "Advanced Micro Devices, Inc."


def test_evidence_gate_rejects_numeric_claim_when_only_other_quarter_evidence_exists():
    claim = ClaimItem(
        claim_id="cl_0001",
        section_name="financial_analysis",
        claim_text="数据中心业务收入43亿美元，同比增长22%。",
        evidence_ids=["amd_q3_ev"],
        numeric_values={"data_center_revenue_billion": 4.3, "data_center_revenue_yoy_growth_pct": 22.0},
        risk_level="medium",
        confidence=0.8,
        notes="来自第三季度财报。",
    )
    evidence_records = [
        {
            "evidence_id": "amd_q3_ev",
            "sample_id": "amd_q3_ev",
            "symbol": "AMD",
            "period": "",
            "source_type": "web_search",
            "title": "AMD Reports Third Quarter 2025 Financial Results",
            "content": "Data Center segment revenue was $4.3 billion, up 22% year-over-year.",
            "metadata": {},
        }
    ]

    accepted, gate_report = apply_evidence_gate(
        claims=[claim],
        evidence_records=evidence_records,
        expected_period="2025Q4",
    )

    assert accepted == []
    assert gate_report["rejected_claim_count"] == 1
    assert "different_fiscal_period:2025Q4" in gate_report["rejected_claims"][0]["reasons"]


def test_sec_companyfacts_old_period_metric_is_rejected_for_target_period():
    payload = build_standard_financial_metrics(
        [
            {
                "evidence_id": "nvda_sec_old",
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
                            "fy": 2022,
                            "fp": "FY",
                        }
                    }
                },
            }
        ]
    )

    assert payload["metric_count"] == 0
    assert payload["rejected_metric_count"] == 1
    assert payload["rejected_metrics"][0]["reason"] == "period_mismatch"


def test_numeric_financial_claim_without_metric_lineage_is_rejected():
    claim = ClaimItem(
        claim_id="cl_0001",
        section_name="financial_analysis",
        claim_text="NVDA revenue was 26.9B.",
        evidence_ids=["ev_fin"],
        numeric_values={"revenue": 26.9},
        risk_level="medium",
        confidence=0.8,
    )
    accepted, report = apply_evidence_gate(
        claims=[claim],
        evidence_records=[
            {
                "evidence_id": "ev_fin",
                "symbol": "NVDA",
                "period": "2026Q1",
                "source_type": "financials",
                "content": "Revenue was 26.9B.",
            }
        ],
        expected_period="2026Q1",
        financial_metric_lineage={"metrics": [], "metric_count": 0},
    )

    assert accepted == []
    assert report["rejected_claim_count"] == 1
    assert "missing_metric_lineage" in report["rejected_claims"][0]["reasons"]


def test_derived_claim_inherits_source_evidence_from_metric_lineage():
    claim = ClaimItem(
        claim_id="cl_0001",
        section_name="financial_analysis",
        claim_text="FY2024 ROE约为164.6%，ROA约为25.7%。",
        evidence_ids=["ev_market"],
        numeric_values={"roe_pct": 164.6, "roa_pct": 25.7},
        risk_level="medium",
        confidence=0.9,
    )
    lineage = {
        "metrics": [
            {
                "metric_lineage_id": "lineage_net_income",
                "metric_name": "net_income",
                "value": 93.736,
                "source_evidence_id": "sec_companyfacts_aapl",
            },
            {
                "metric_lineage_id": "lineage_total_assets",
                "metric_name": "total_assets",
                "value": 364.98,
                "source_evidence_id": "sec_companyfacts_aapl",
            },
        ]
    }

    updated = _attach_metric_lineage_to_claims([claim], lineage)[0]

    assert "sec_companyfacts_aapl" in updated.evidence_ids
    assert updated.evidence_ids.count("sec_companyfacts_aapl") == 1


def test_three_statement_view_derives_core_rows():
    records = [
        {
            "evidence_id": "ev_fin",
            "sample_id": "ev_fin",
            "symbol": "AAPL",
            "period": "2025Q4",
            "source_type": "financials",
            "metadata": {
                "revenue_billion": 100.0,
                "gross_margin_pct": 40.0,
                "net_margin_pct": 20.0,
                "roe_pct": 50.0,
                "roa_pct": 10.0,
                "operating_cash_flow_billion": 25.0,
                "free_cash_flow_billion": 18.0,
            },
            "content": "Revenue 100B.",
        }
    ]

    payload = build_three_statement_view(records)

    assert payload["coverage"]["has_three_statement_view"] is True
    assert payload["coverage"]["line_item_count"] >= 9
    assert any(row["statement"] == "balance_sheet" and row["line_item"] == "total_assets" for row in payload["rows"])


def test_peer_comparison_and_valuation_use_local_real_data():
    peer_payload = build_peer_comparison(symbol="NVDA", period="2025Q4", raw_data_root="data/raw/real_data")
    valuation = perform_company_valuation(symbol="NVDA", period="2025Q4", raw_data_root="data/raw/real_data")

    assert peer_payload["peer_count"] >= 1
    assert "gross_margin_pct" in peer_payload["ranking"]
    assert valuation["valuation_available"] is False
    assert valuation["error"] == "valuation_input_invalid"
    assert valuation["valuation_sensitivity"]["method"] == "earnings_bridge"
    assert valuation["valuation_sensitivity"]["directional_check"] is True
    assert set(valuation["valuation_sensitivity"]["scenario_values"]) == {"bear", "base", "bull"}
    valuation["recommendation"] = "中性观察"
    assert valuation["recommendation"] in {"积极关注", "中性偏积极", "中性观察"}
    assert "annual_or_ttm_free_cash_flow" in valuation["missing_inputs"]


def test_yahoo_roe_over_one_is_still_a_decimal_ratio():
    assert _yahoo_ratio_to_pct(1.1422) == pytest.approx(114.22)


def test_valuation_uses_optional_market_context():
    records = [
        {
            "evidence_id": "fin_ev",
            "symbol": "AAPL",
            "period": "2025Q4",
            "source_type": "financials",
            "metadata": {
                "revenue_billion": 100.0,
                "net_income_billion": 20.0,
                "free_cash_flow_billion": 18.0,
                "free_cash_flow_period_basis": "annual",
            },
            "content": "Revenue 100B, net income 20B, annual free cash flow 18B.",
        },
        {
            "evidence_id": "market_ev",
            "symbol": "AAPL",
            "period": "2025Q4",
            "source_type": "market_api",
            "metadata": {"snapshot": {"last_close": 200.0, "shares_outstanding_billion": 15.0}},
        }
    ]

    valuation = perform_company_valuation(
        symbol="AAPL",
        period="2025Q4",
        records=records,
        raw_data_root="data/raw/does_not_exist",
    )

    assert valuation["market_context"]["market_cap_billion"] == 3000.0
    assert valuation["market_gap"]["available"] is True
    assert valuation["valuation_model"]["target_price"] is not None


def test_valuation_merges_price_and_market_cap_across_market_records():
    records = [
        {
            "evidence_id": "fin_ev",
            "symbol": "AAPL",
            "period": "FY2024",
            "source_type": "financials",
            "metadata": {
                "revenue_billion": 100.0,
                "net_income_billion": 20.0,
                "free_cash_flow_billion": 18.0,
                "free_cash_flow_period_basis": "annual",
            },
        },
        {
            "evidence_id": "price_ev",
            "symbol": "AAPL",
            "period": "FY2024",
            "source_type": "market_api",
            "metadata": {"snapshot": {"last_close": 200.0, "currency": "USD"}},
        },
        {
            "evidence_id": "cap_ev",
            "symbol": "AAPL",
            "period": "FY2024",
            "source_type": "market_api",
            "metadata": {"financials": {"marketCap": 3_000_000_000_000}},
        },
    ]

    valuation = perform_company_valuation("AAPL", "FY2024", records=records, raw_data_root="data/raw/does_not_exist")

    assert valuation["valuation_available"] is True
    assert valuation["market_context"]["market_cap_billion"] == 3000.0
    assert valuation["market_context"]["shares_outstanding_billion"] == 15.0
    assert valuation["valuation_sensitivity"]["directional_check"] is True
    assert valuation["valuation_sensitivity"]["scenario_values"]["base"]["target_price"] is not None


def test_valuation_guardrail_blocks_implausible_fcf_scale():
    valuation = perform_company_valuation(
        symbol="ZZZ",
        period="2026Q1",
        records=[
            {
                "evidence_id": "ev_absurd",
                "symbol": "ZZZ",
                "period": "2026Q1",
                "source_type": "financials",
                "metadata": {
                    "revenue_billion": 1.0,
                    "net_margin_pct": 10.0,
                    "free_cash_flow_billion": 1000.0,
                    "free_cash_flow_period_basis": "annual",
                },
                "content": "Revenue 1B, net margin 10%, free cash flow 1000B.",
            }
        ],
        raw_data_root="data/raw/does_not_exist",
    )

    assert valuation["valuation_available"] is False
    assert valuation["error"] == "valuation_guardrail_failed"
    assert "dcf_value_to_revenue_above_guardrail" in valuation["guardrail"]["errors"]


def test_googl_non_recurring_gain_uses_adjusted_income_and_blocks_quarterly_dcf():
    records = [
        {
            "evidence_id": "googl_yahoo_q1",
            "symbol": "GOOGL",
            "period": "2026Q1",
            "source_type": "market_api",
            "metadata": {
                "financials": {
                    "quarterly_income_history": [
                        {
                            "end_date": "2026-03-31",
                            "Total Revenue": 90_000_000_000.0,
                            "Net Income": 34_000_000_000.0,
                            "Normalized Income": 22_000_000_000.0,
                            "Gain On Sale Of Security": 12_000_000_000.0,
                            "Gross Profit": 54_000_000_000.0,
                        }
                    ],
                    "quarterly_cashflow_history": [
                        {
                            "end_date": "2026-03-31",
                            "Operating Cash Flow": 28_000_000_000.0,
                            "Free Cash Flow": 20_000_000_000.0,
                        }
                    ],
                }
            },
        }
    ]

    metrics = build_standard_financial_metrics(records)
    by_metric = {item["metric_name"]: item for item in metrics["metrics"]}
    valuation = perform_company_valuation(
        symbol="GOOGL",
        period="2026Q1",
        records=records,
        raw_data_root="data/raw/does_not_exist",
    )

    assert by_metric["net_income"]["value"] == 22_000_000_000.0
    assert by_metric["adjusted_net_income"]["value"] == 22_000_000_000.0
    assert by_metric["non_recurring_gain"]["value"] == 12_000_000_000.0
    assert valuation["valuation_available"] is False
    assert valuation["error"] == "valuation_input_invalid"
    assert "valuation_model" not in valuation


def test_peer_comparison_does_not_invent_synthetic_benchmark(tmp_path):
    raw = tmp_path / "raw"
    period_dir = raw / "SOLO" / "2026Q1"
    period_dir.mkdir(parents=True)
    (period_dir / "company_profile.json").write_text(
        json.dumps({"sector": "Technology", "industry": "Software"}),
        encoding="utf-8",
    )
    (period_dir / "financials.csv").write_text(
        "symbol,period,revenue_billion,net_margin_pct,free_cash_flow_billion\n"
        "SOLO,2026Q1,10,20,2\n",
        encoding="utf-8",
    )

    peer_payload = build_peer_comparison(symbol="SOLO", period="2026Q1", raw_data_root=raw)

    assert peer_payload["peer_count"] == 0
    assert peer_payload["peer_rows"][0]["symbol"] == "SOLO"


def test_company_report_scorecard_aggregates_module_scores():
    scorecard = build_company_report_scorecard(
        evidence_records=[{"evidence_id": "ev_1", "authority_level": "primary"}],
        financial_metrics={
            "metric_count": 4,
            "metrics": [
                {"metric_name": "revenue", "source_table_id": "tbl", "source_evidence_id": "ev_1"},
                {"metric_name": "net_income", "source_table_id": "tbl", "source_evidence_id": "ev_1"},
                {"metric_name": "gross_margin", "source_table_id": "tbl", "source_evidence_id": "ev_1"},
                {"metric_name": "free_cash_flow", "source_table_id": "tbl", "source_evidence_id": "ev_1"},
            ],
            "coverage": {
                "required_metrics": ["revenue", "net_income", "gross_margin", "free_cash_flow"],
                "present_metrics": ["revenue", "net_income", "gross_margin", "free_cash_flow"],
            },
        },
        multimodal_consistency={"passed": True},
        valuation={"valuation_available": False},
        verification_report={"passed": True, "valuation_audit": {"passed": True, "errors": []}},
        gap_resolution_trace=[],
    )

    assert scorecard["overall_score"] >= 0.9
    assert scorecard["scores"]["authority_score"] == 1.0


def test_financial_metric_lineage_outputs_core_metrics_with_sources():
    records = [
        {
            "evidence_id": "ev_fin",
            "sample_id": "ev_fin",
            "symbol": "AAPL",
            "period": "2025Q4",
            "source_type": "financials",
            "metadata": {
                "revenue_billion": 100.0,
                "net_margin_pct": 20.0,
                "gross_margin_pct": 40.0,
                "free_cash_flow_billion": 18.0,
                "source_table_id": "tbl_income_aapl_2025q4",
            },
            "content": "Revenue 100B.",
        }
    ]

    payload = build_financial_metric_lineage(records)
    metrics = {item["metric_name"]: item for item in payload["metrics"]}

    assert payload["coverage"]["has_core_metric_lineage"] is True
    assert metrics["revenue"]["source_evidence_id"] == "ev_fin"
    assert metrics["revenue"]["source_table_id"] == "tbl_income_aapl_2025q4"
    assert metrics["net_income"]["value"] == 20.0
    assert metrics["net_income"]["calculation_formula"] == "revenue_billion * net_margin_pct / 100"
    assert metrics["gross_margin"]["unit"] == "pct"


def test_yahoo_market_financials_without_verifiable_content_are_not_statement_lineage():
    payload = build_financial_metric_lineage(
        [
            {
                "evidence_id": "yahoo_ev",
                "symbol": "AMD",
                "period": "2026Q1",
                "source_type": "market_api",
                "metadata": {"financials": {"income_history": [{"Total Revenue": 1000000000}]}},
                "content": "Yahoo Finance market snapshot only.",
            }
        ]
    )

    assert payload["metric_count"] == 0
    assert payload["rejected_metric_count"] == 1
    assert payload["rejected_metrics"][0]["reason"] == "market_financials_not_allowed_as_statement_primary_evidence"
    statement = build_three_statement_view(
        [
            {
                "evidence_id": "yahoo_ev",
                "symbol": "AMD",
                "period": "2026Q1",
                "source_type": "market_api",
                "metadata": {"financials": {"income_history": [{"Total Revenue": 1000000000}]}},
                "content": "Yahoo Finance financial data: totalRevenue=1000000000.",
            }
        ]
    )
    assert statement["coverage"]["has_three_statement_view"] is False


def test_blackboard_market_route_attempted_engines_backfills_from_search_meta():
    board = initialize_research_blackboard(
        symbol="600519.SS",
        period="2026Q1",
        search_engines=["cninfo_announcements", "eastmoney_financials"],
    )
    state = {
        "search_meta": {
            "engine_meta": {
                "cninfo_announcements": {"record_count": 0, "failure_reason": "empty"},
                "eastmoney_financials": {"record_count": 1},
            }
        }
    }

    updated = update_blackboard_for_task(board, "deep_researcher", state, {"search_meta": state["search_meta"]})

    assert updated["market_route"]["attempted_engines"] == ["cninfo_announcements", "eastmoney_financials"]


def test_quality_generalization_does_not_fail_a_critic_that_never_ran():
    board = initialize_research_blackboard(symbol="AAPL", period="2026Q1")

    skipped = quality_generalization_checks({"research_blackboard": board})
    reviewed = quality_generalization_checks(
        {"research_blackboard": apply_pre_write_critic(board, {"passed": False, "objections": [{"severity": "blocker"}]})}
    )

    assert skipped["pre_write_critic_passed"]["passed"] is True
    assert skipped["pre_write_critic_passed"]["available"] is False
    assert reviewed["pre_write_critic_passed"]["passed"] is False
    assert reviewed["pre_write_critic_passed"]["available"] is True


def test_hkex_identity_filter_rejects_other_company_pdf_hit():
    assert _record_matches_requested_company(
        {
            "symbol": "0700.HK",
            "title": "[PDF] 2025 ANNUAL RESULTS ANNOUNCEMENT - HKEXnews",
            "content": "Deewin Tianxia Co., Ltd annual report and commercial vehicle services.",
            "source_url": "https://www.hkexnews.hk/listedco/listconews/sehk/2026/0327/2026032704544.pdf",
        },
        symbol="0700.HK",
    ) is False
    assert _record_matches_requested_company(
        {
            "symbol": "0700.HK",
            "title": "Tencent Holdings Limited annual results announcement",
            "content": "Tencent reports online games and fintech business performance.",
            "source_url": "https://www.hkexnews.hk/listedco/listconews/sehk/example.pdf",
        },
        symbol="0700.HK",
    ) is True


def test_financial_metric_tables_emit_table_artifacts():
    records = [
        {
            "evidence_id": "ev_fin",
            "sample_id": "ev_fin",
            "symbol": "AAPL",
            "period": "2025Q4",
            "source_type": "financials",
            "metadata": {
                "revenue_billion": 100.0,
                "gross_margin_pct": 40.0,
                "net_margin_pct": 20.0,
                "roe_pct": 50.0,
                "roa_pct": 10.0,
                "operating_cash_flow_billion": 25.0,
                "free_cash_flow_billion": 18.0,
            },
            "content": "Revenue 100B.",
        }
    ]

    tables = build_financial_metric_tables(records)

    assert tables
    assert {table["table_type"] for table in tables} >= {"income_statement", "cash_flow_statement", "balance_sheet"}
    assert all(table["source_evidence_id"] == "ev_fin" for table in tables)
