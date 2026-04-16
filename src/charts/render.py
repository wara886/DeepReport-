"""Stage 5 chart orchestration and report integration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import pandas as pd

from src.charts.bar_chart import render_bar_chart
from src.charts.line_chart import render_line_chart
from src.charts.table_chart import render_table_chart

CHARTS_START = "<!-- charts:start -->"
CHARTS_END = "<!-- charts:end -->"


def _safe_read_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def render_all_charts(
    features_root: str | Path = "data/features",
    chart_output_dir: str | Path = "data/outputs/charts",
    metadata_path: str | Path = "data/outputs/chart_metadata.json",
) -> List[Dict[str, str]]:
    features_root = Path(features_root)
    chart_dir = Path(chart_output_dir)
    chart_dir.mkdir(parents=True, exist_ok=True)

    ratio_df = _safe_read_parquet(features_root / "financial_ratios.parquet")
    risk_df = _safe_read_parquet(features_root / "risk_signals.parquet")
    trend_df = _safe_read_parquet(features_root / "trend_analysis.parquet")

    metadata: List[Dict[str, str]] = []

    # Line chart: revenue by symbol
    if not ratio_df.empty and "revenue_billion" in ratio_df.columns:
        line_data = (
            ratio_df.dropna(subset=["revenue_billion"])
            .groupby("symbol", dropna=False)["revenue_billion"]
            .max()
            .reset_index()
        )
        points = [(str(r["symbol"]), float(r["revenue_billion"])) for _, r in line_data.iterrows()]
        line_path = render_line_chart(points, chart_dir / "revenue_line.png", title="Revenue (B) by Symbol")
        metadata.append(
            {
                "chart_id": "revenue_line",
                "chart_type": "line",
                "title": "Revenue (B) by Symbol",
                "output_path": str(line_path),
                "source_fields": "symbol,revenue_billion",
            }
        )

    # Bar chart: risk ratio by symbol
    if not risk_df.empty and "risk_ratio" in risk_df.columns:
        bars = [(str(r["symbol"]), float(r["risk_ratio"])) for _, r in risk_df.iterrows()]
        bar_path = render_bar_chart(bars, chart_dir / "risk_ratio_bar.png", title="Risk Ratio by Symbol")
        metadata.append(
            {
                "chart_id": "risk_ratio_bar",
                "chart_type": "bar",
                "title": "Risk Ratio by Symbol",
                "output_path": str(bar_path),
                "source_fields": "symbol,risk_ratio",
            }
        )

    # Table chart: evidence coverage
    if not trend_df.empty:
        cols = ["symbol", "period", "evidence_count", "unique_sources"]
        existing_cols = [c for c in cols if c in trend_df.columns]
        rows = []
        for _, row in trend_df[existing_cols].iterrows():
            rows.append([str(row[c]) for c in existing_cols])
        table_path = render_table_chart(existing_cols, rows, chart_dir / "coverage_table.png", title="Evidence Coverage")
        metadata.append(
            {
                "chart_id": "coverage_table",
                "chart_type": "table",
                "title": "Evidence Coverage",
                "output_path": str(table_path),
                "source_fields": ",".join(existing_cols),
            }
        )

    meta_out = Path(metadata_path)
    meta_out.parent.mkdir(parents=True, exist_ok=True)
    meta_out.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def attach_charts_to_report(report_path: str | Path, metadata: List[Dict[str, str]]) -> Path:
    report_path = Path(report_path)
    if not report_path.exists():
        raise FileNotFoundError(f"Report not found: {report_path}")

    original = report_path.read_text(encoding="utf-8")
    chart_lines = [CHARTS_START, "## Charts", ""]
    if metadata:
        for item in metadata:
            chart_lines.append(f"- {item['title']}: `{item['output_path']}`")
    else:
        chart_lines.append("- No charts generated.")
    chart_lines.extend(["", CHARTS_END])
    block = "\n".join(chart_lines)

    if CHARTS_START in original and CHARTS_END in original:
        start = original.index(CHARTS_START)
        end = original.index(CHARTS_END) + len(CHARTS_END)
        updated = original[:start].rstrip() + "\n\n" + block + "\n"
    else:
        updated = original.rstrip() + "\n\n" + block + "\n"

    report_path.write_text(updated, encoding="utf-8")
    return report_path

