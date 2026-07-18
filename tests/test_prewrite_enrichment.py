from src.report.prewrite_enrichment import enrich_prewrite_inputs
from src.evaluation.valuation_audit import audit_valuation_model


def test_prewrite_enrichment_rebuilds_valuation_peer_and_chart_claims():
    canonical = {
        "schema_version": "canonical_metrics.v3",
        "canonical_metrics": {
            "revenue": _metric("revenue", 391.035, "financial"),
            "net_income": _metric("net_income", 93.736, "financial"),
            "total_assets": _metric("total_assets", 364.98, "financial"),
            "total_liabilities": _metric("total_liabilities", 308.03, "financial"),
            "total_equity": _metric("total_equity", 56.95, "financial"),
            "shares_outstanding": _metric("shares_outstanding", 15.116786, "financial", unit="billion_shares"),
            "operating_cash_flow": _metric("operating_cash_flow", 118.254, "financial"),
            "free_cash_flow": _metric("free_cash_flow", 108.807, "financial"),
        },
    }
    peers = [
        _peer("AAPL", 27.15, 16.6, True),
        _peer("MSFT", 39.34, 18.3),
        _peer("GOOGL", 37.92, 21.8),
        _peer("META", 32.84, 33.1),
    ]
    result = enrich_prewrite_inputs(
        analysis_artifacts={
            "peer_context": {
                "peer_rows": [],
                "period_mismatch_rows": peers,
                "status": "period_mismatch",
            }
        },
        claims=[
            {"claim_id": "old-valuation", "section_name": "valuation", "claim_text": "估值不可用"},
            {"claim_id": "old-peer", "section_name": "peer_compare", "claim_text": "同行数据缺失"},
        ],
        evidence_records=[{
            "evidence_id": "market-price",
            "symbol": "AAPL",
            "source_type": "market_api",
            "metadata": {
                "parent_metadata": {
                    "snapshot": {"last_close": 315.32, "latest_date": "2026-07-10", "currency": "USD"}
                }
            },
        }],
        canonical_metrics=canonical,
        tables=[],
        symbol="AAPL",
        period="FY2024",
    )

    artifacts = result["analysis_artifacts"]
    assert artifacts["valuation_model"]["valuation_available"] is True
    assert artifacts["valuation_model"]["relative_valuation"]["multiples"]["pe"]["multiple"] > 0
    assert len(artifacts["valuation_sensitivity"]["rows"]) == 3
    valuation_audit = audit_valuation_model({
        "valuation_available": True,
        "valuation_model": artifacts["valuation_model"],
        "valuation_sensitivity": artifacts["valuation_sensitivity"],
    })
    assert valuation_audit["passed"] is True
    assert valuation_audit["errors"] == []
    assert artifacts["peer_context"]["comparison_period"] == "CURRENT_TTM"
    assert len(artifacts["peer_context"]["peer_rows"]) == 4

    claims = {item["section_name"]: item for item in result["claims"]}
    assert "估值不可用" not in claims["valuation"]["claim_text"]
    assert claims["valuation"]["numeric_values"]["pe_ratio"] > 0
    assert claims["valuation_sensitivity"]["numeric_values"]["bear_target_price"] > 0
    assert claims["peer_compare"]["numeric_values"]["peer_median_net_margin_pct"] > 0
    assert claims["financial_analysis"]["numeric_values"]["free_cash_flow_billion"] == 108.807
    assert len([item for item in result["evidence_records"] if item["evidence_id"].startswith("peer_current_ttm_")]) == 4
    assert any(item["source_type"] == "valuation_model" for item in result["evidence_records"])


def _metric(name, value, evidence_id, unit="USD_billion"):
    return {
        "metric_name": name,
        "metric_id": f"metric-{name}",
        "value": value,
        "unit": unit,
        "currency": "USD",
        "source_evidence_id": evidence_id,
    }


def _peer(symbol, margin, growth, is_target=False):
    return {
        "symbol": symbol,
        "company_name": symbol,
        "is_target": is_target,
        "industry": "Consumer Electronics",
        "net_margin_pct": margin,
        "gross_margin_pct": 45.0,
        "revenue_growth_pct": growth,
        "roe_pct": 30.0,
        "data_period": "current_ttm",
        "source_url": f"https://finance.yahoo.com/quote/{symbol}",
    }
