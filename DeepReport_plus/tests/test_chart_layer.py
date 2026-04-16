import json
from pathlib import Path

import pandas as pd

from src.charts.render import attach_charts_to_report, render_all_charts


def _write_feature_inputs(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {"symbol": "AAPL", "revenue_billion": 126.3, "gross_margin_pct": 46.8},
            {"symbol": "MSFT", "revenue_billion": 69.2, "gross_margin_pct": None},
        ]
    ).to_parquet(root / "financial_ratios.parquet", index=False)
    pd.DataFrame(
        [
            {"symbol": "AAPL", "risk_ratio": 0.0},
            {"symbol": "MSFT", "risk_ratio": 0.25},
        ]
    ).to_parquet(root / "risk_signals.parquet", index=False)
    pd.DataFrame(
        [
            {"symbol": "AAPL", "period": "2025Q4", "evidence_count": 4, "unique_sources": 4},
            {"symbol": "MSFT", "period": "2025Q4", "evidence_count": 4, "unique_sources": 4},
        ]
    ).to_parquet(root / "trend_analysis.parquet", index=False)


def test_render_all_charts_and_attach(tmp_path: Path):
    features_root = tmp_path / "features"
    _write_feature_inputs(features_root)

    chart_dir = tmp_path / "charts"
    metadata_path = tmp_path / "chart_metadata.json"
    report_path = tmp_path / "report.md"
    report_path.write_text("# Sample Report\n", encoding="utf-8")

    metadata = render_all_charts(features_root=features_root, chart_output_dir=chart_dir, metadata_path=metadata_path)
    assert len(metadata) >= 3
    assert metadata_path.exists()

    meta = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert any(item["chart_type"] == "line" for item in meta)
    assert any(item["chart_type"] == "bar" for item in meta)
    assert any(item["chart_type"] == "table" for item in meta)

    attach_charts_to_report(report_path, metadata)
    updated = report_path.read_text(encoding="utf-8")
    assert "## Charts" in updated
    assert "charts:start" in updated

