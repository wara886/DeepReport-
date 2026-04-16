"""Peer comparison feature generation."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


_TRUST_WEIGHT = {"high": 1.0, "medium": 0.6, "low": 0.3}


def build_peer_compare(manifest_df: pd.DataFrame) -> pd.DataFrame:
    working = manifest_df.copy()
    working["trust_weight"] = (
        working["trust_level"].astype(str).str.lower().map(_TRUST_WEIGHT).fillna(0.5)
    )

    grouped = (
        working.groupby("symbol", dropna=False)
        .agg(
            evidence_count=("sample_id", "count"),
            avg_trust_weight=("trust_weight", "mean"),
            unique_source_types=("source_type", "nunique"),
        )
        .reset_index()
    )

    grouped["peer_rank"] = grouped["avg_trust_weight"].rank(method="dense", ascending=False).astype(int)
    return grouped


def save_peer_compare(df: pd.DataFrame, output_path: str | Path = "data/features/peer_compare.parquet") -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    return out

