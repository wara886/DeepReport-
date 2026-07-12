"""Programmatic trend feature generation."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def build_trend_features(manifest_df: pd.DataFrame) -> pd.DataFrame:
    expected_columns = ["symbol", "period", "evidence_count", "unique_sources", "latest_publish_time", "sample_ids"]
    if manifest_df.empty:
        return pd.DataFrame(columns=expected_columns)
    df = manifest_df.copy()
    for column in ["symbol", "period", "source_type", "publish_time"]:
        if column not in df.columns:
            df[column] = ""
    for column in ["symbol", "period", "source_type", "publish_time"]:
        df[column] = df[column].astype("string").fillna("")
    if "sample_id" not in df.columns:
        if "evidence_id" in df.columns:
            df["sample_id"] = df["evidence_id"]
        else:
            df["sample_id"] = [f"record_{index + 1}" for index in range(len(df))]
    grouped = (
        df.groupby(["symbol", "period"], dropna=False)
        .agg(
            evidence_count=("sample_id", "count"),
            unique_sources=("source_type", "nunique"),
            latest_publish_time=("publish_time", "max"),
            sample_ids=("sample_id", lambda s: "|".join(sorted({str(x) for x in s.dropna().tolist()}))),
        )
        .reset_index()
    )
    return grouped[expected_columns]


def save_trend_features(df: pd.DataFrame, output_path: str | Path = "data/features/trend_analysis.parquet") -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    return out
