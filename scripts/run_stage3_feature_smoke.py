#!/usr/bin/env python3
"""Stage 3 smoke runner: build programmatic feature outputs."""

from __future__ import annotations

from pathlib import Path
import json
import sys

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.features.financial_ratios import build_financial_ratios, save_financial_ratios
from src.features.peer_compare import build_peer_compare, save_peer_compare
from src.features.risk_signals import build_risk_signals, save_risk_signals
from src.features.trend_analysis import build_trend_features, save_trend_features


def _load_curated_manifest() -> pd.DataFrame:
    paths = sorted(Path("data/curated").glob("*.parquet"))
    if not paths:
        raise FileNotFoundError("No curated parquet files found. Run Stage 2 smoke first.")
    frames = [pd.read_parquet(p) for p in paths]
    return pd.concat(frames, ignore_index=True)


def main() -> int:
    manifest_df = _load_curated_manifest()

    ratio_df = build_financial_ratios(manifest_df)
    trend_df = build_trend_features(manifest_df)
    peer_df = build_peer_compare(manifest_df)
    risk_df = build_risk_signals(manifest_df)

    ratio_path = save_financial_ratios(ratio_df)
    trend_path = save_trend_features(trend_df)
    peer_path = save_peer_compare(peer_df)
    risk_path = save_risk_signals(risk_df)

    report = {
        "input_rows": int(len(manifest_df)),
        "outputs": {
            "financial_ratios_rows": int(len(ratio_df)),
            "trend_analysis_rows": int(len(trend_df)),
            "peer_compare_rows": int(len(peer_df)),
            "risk_signals_rows": int(len(risk_df)),
        },
        "files": [
            str(ratio_path),
            str(trend_path),
            str(peer_path),
            str(risk_path),
        ],
    }

    out_report = Path("data/features/feature_report.json")
    out_report.parent.mkdir(parents=True, exist_ok=True)
    out_report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[stage3] report -> {out_report}")
    for fp in report["files"]:
        print(f"[stage3] feature -> {fp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

