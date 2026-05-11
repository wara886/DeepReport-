from pathlib import Path

import pandas as pd

from src.agents.deep_analyze_agent import apply_evidence_gate
from src.data.company_universe import resolve_company_identifier_with_diagnostics, resolve_symbol
from src.schemas.claim import ClaimItem
from src.features.company_valuation import build_peer_comparison, perform_company_valuation
from src.features.financial_metric_lineage import build_financial_metric_lineage, build_financial_metric_tables
from src.features.financial_ratios import build_financial_ratios
from src.features.financial_statements import build_three_statement_view
from src.features.peer_compare import build_peer_compare
from src.features.risk_signals import build_risk_signals
from src.features.trend_analysis import build_trend_features


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
    assert valuation["valuation_available"] is True
    assert valuation["blended_equity_value_billion"] > 0
    assert valuation["recommendation"] in {"积极关注", "中性偏积极", "中性观察"}


def test_valuation_uses_optional_market_context():
    records = [
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
        raw_data_root="data/raw/real_data",
    )

    assert valuation["market_context"]["market_cap_billion"] == 3000.0
    assert valuation["market_gap"]["available"] is True


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
