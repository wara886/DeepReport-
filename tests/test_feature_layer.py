from pathlib import Path

import pandas as pd

from src.features.financial_ratios import build_financial_ratios
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

