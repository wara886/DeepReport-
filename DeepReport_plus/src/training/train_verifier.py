"""Offline verifier training entry for Stage 9."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def train_verifier(
    dataset_path: str = "data/outputs/training/verifier/dataset.parquet",
    checkpoint_path: str = "data/outputs/checkpoints/verifier_checkpoint.json",
) -> str:
    ds = Path(dataset_path)
    if not ds.exists():
        raise FileNotFoundError(f"dataset not found: {ds}")

    df = pd.read_parquet(ds)
    threshold = 0.5
    if "confidence" in df.columns and len(df) > 0:
        threshold = float(df["confidence"].median())

    checkpoint = {
        "model": "verifier",
        "trained": True,
        "rows": int(len(df)),
        "confidence_threshold": threshold,
    }

    out = Path(checkpoint_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")
    return str(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="Train verifier from offline dataset.")
    parser.add_argument("--dataset-path", default="data/outputs/training/verifier/dataset.parquet")
    parser.add_argument("--checkpoint-path", default="data/outputs/checkpoints/verifier_checkpoint.json")
    args = parser.parse_args()

    out = train_verifier(dataset_path=args.dataset_path, checkpoint_path=args.checkpoint_path)
    print(f"[stage9] verifier checkpoint: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

