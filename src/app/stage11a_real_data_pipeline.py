"""Stage 11A real-data minimal closed-loop pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import pandas as pd

from src.app.pipeline import run_pipeline
from src.charts.render import attach_charts_to_report, render_all_charts
from src.data.fetch_company_profile import CompanyProfileFetcher
from src.data.fetch_financials import FinancialsFetcher
from src.data.fetch_filings import FilingsFetcher
from src.data.fetch_market import MarketFetcher
from src.data.fetch_news import NewsFetcher
from src.data.manifest import build_manifest, write_manifest_json, write_manifest_parquet
from src.features.financial_ratios import build_financial_ratios, save_financial_ratios
from src.features.peer_compare import build_peer_compare, save_peer_compare
from src.features.risk_signals import build_risk_signals, save_risk_signals
from src.features.trend_analysis import build_trend_features, save_trend_features
from src.templates.exporter import export_reports
from src.utils.config import load_config


def _concat_parquet_folder(folder: Path, exclude_names: List[str] | None = None) -> pd.DataFrame:
    exclude_names = exclude_names or []
    paths = [p for p in sorted(folder.glob("*.parquet")) if p.name not in exclude_names]
    if not paths:
        return pd.DataFrame()
    frames = [pd.read_parquet(p) for p in paths]
    return pd.concat(frames, ignore_index=True)


def run_real_data_pipeline(config_path: str = "configs/local_real_smoke.yaml") -> Dict[str, str]:
    cfg = load_config(config_path)
    real_cfg = dict(cfg.get("real_data", {}))
    data_mode = str(real_cfg.get("data_mode", "local_file_real"))
    symbol = str(real_cfg.get("symbol", "")).strip()
    period = str(real_cfg.get("period", "")).strip()
    raw_root = str(real_cfg.get("raw_root", "data/raw/real_data"))
    curated_root = Path(str(real_cfg.get("curated_root", "data/curated_real")))
    features_root = Path(str(real_cfg.get("features_root", "data/features_real")))
    outputs_root = Path(str(real_cfg.get("outputs_root", "data/outputs_real")))
    reports_root = Path(str(real_cfg.get("reports_root", "data/reports_real")))
    source_cfg = dict(real_cfg.get("sources", {}))

    if data_mode == "mock":
        fetchers = [
            FinancialsFetcher(mode="mock"),
            MarketFetcher(mode="mock"),
            NewsFetcher(mode="mock"),
            FilingsFetcher(mode="mock"),
        ]
    elif data_mode == "local_file_real":
        fetchers = [
            CompanyProfileFetcher(
                mode=data_mode,
                real_data_root=raw_root,
                symbol=symbol,
                period=period,
                real_file_path=str(Path(raw_root) / symbol / period / source_cfg["company_profile"]["filename"]),
            ),
            FinancialsFetcher(
                mode=data_mode,
                real_data_root=raw_root,
                symbol=symbol,
                period=period,
                real_file_path=str(Path(raw_root) / symbol / period / source_cfg["financials"]["filename"]),
            ),
            MarketFetcher(
                mode=data_mode,
                real_data_root=raw_root,
                symbol=symbol,
                period=period,
                real_file_path=str(Path(raw_root) / symbol / period / source_cfg["market"]["filename"]),
            ),
            NewsFetcher(
                mode=data_mode,
                real_data_root=raw_root,
                symbol=symbol,
                period=period,
                real_file_path=str(Path(raw_root) / symbol / period / source_cfg["news"]["filename"]),
            ),
            FilingsFetcher(
                mode=data_mode,
                real_data_root=raw_root,
                symbol=symbol,
                period=period,
                real_file_path=str(Path(raw_root) / symbol / period / source_cfg["filings"]["filename"]),
            ),
        ]
    else:
        raise ValueError(f"Unsupported data_mode for Stage11A: {data_mode}")

    curated_root.mkdir(parents=True, exist_ok=True)
    all_manifest_rows: List[Dict[str, object]] = []
    for fetcher in fetchers:
        raw_rows = fetcher.fetch()
        manifest_rows = build_manifest(
            raw_rows,
            source_type=fetcher.source_type,
            strict_required=(data_mode == "local_file_real"),
        )
        write_manifest_parquet(manifest_rows, curated_root / f"{fetcher.source_type}.parquet")
        all_manifest_rows.extend(manifest_rows)

    write_manifest_parquet(all_manifest_rows, curated_root / "real_data_manifest.parquet")
    write_manifest_json(all_manifest_rows, curated_root / "real_data_manifest.json")

    manifest_df = _concat_parquet_folder(curated_root, exclude_names=["real_data_manifest.parquet"])

    ratio_df = build_financial_ratios(manifest_df)
    trend_df = build_trend_features(manifest_df)
    peer_df = build_peer_compare(manifest_df)
    risk_df = build_risk_signals(manifest_df)

    save_financial_ratios(ratio_df, features_root / "financial_ratios.parquet")
    save_trend_features(trend_df, features_root / "trend_analysis.parquet")
    save_peer_compare(peer_df, features_root / "peer_compare.parquet")
    save_risk_signals(risk_df, features_root / "risk_signals.parquet")
    feature_report = {
        "input_rows": int(len(manifest_df)),
        "outputs": {
            "financial_ratios_rows": int(len(ratio_df)),
            "trend_analysis_rows": int(len(trend_df)),
            "peer_compare_rows": int(len(peer_df)),
            "risk_signals_rows": int(len(risk_df)),
        },
    }
    (features_root / "feature_report_real.json").write_text(
        json.dumps(feature_report, indent=2), encoding="utf-8"
    )

    generation_cfg = dict(cfg.get("generation", {}))
    pipeline_outputs = run_pipeline(
        output_dir=str(outputs_root),
        report_dir=str(reports_root),
        features_root=str(features_root),
        writer_mode=str(generation_cfg.get("writer_mode", "template_only")),
        writer_backend=str(generation_cfg.get("backend", "mock")),
        writer_backend_config_path=str(generation_cfg.get("backend_config_path", "configs/model_backends.yaml")),
        writer_debug_path=str(reports_root / "writer_debug.json"),
    )

    chart_meta = render_all_charts(
        features_root=str(features_root),
        chart_output_dir=str(outputs_root / "charts"),
        metadata_path=str(outputs_root / "chart_metadata.json"),
    )
    attach_charts_to_report(reports_root / "report.md", chart_meta)

    export_outputs = export_reports(
        claim_path=Path(pipeline_outputs["claim_table"]),
        chart_meta_path=outputs_root / "chart_metadata.json",
        report_dir=reports_root,
    )

    return {
        "curated_root": str(curated_root),
        "features_root": str(features_root),
        "outputs_root": str(outputs_root),
        "reports_root": str(reports_root),
        **export_outputs,
    }
