"""Offline reranker training entry for Stage 11C."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict

import pandas as pd

from src.utils.config import load_config


def _resolve_train_paths(
    cloud_config_path: str,
    reranker_config_path: str,
    dataset_path: str | None,
    checkpoint_path: str | None,
) -> Dict[str, str]:
    cloud_cfg = load_config(cloud_config_path)
    reranker_cfg = load_config(reranker_config_path)
    del cloud_cfg

    r_cfg = dict(reranker_cfg.get("reranker", {}))
    training_cfg = dict(r_cfg.get("training", {}))

    return {
        "dataset_path": str(dataset_path or training_cfg.get("dataset_path", "data/outputs/training/reranker/dataset.parquet")),
        "checkpoint_path": str(checkpoint_path or r_cfg.get("checkpoint_path", "data/outputs/checkpoints/reranker_checkpoint.json")),
        "model_name": str(r_cfg.get("model_name", "reranker-placeholder")),
        "batch_size": str(r_cfg.get("batch_size", 8)),
    }


def train_reranker(
    dataset_path: str | None = None,
    checkpoint_path: str | None = None,
    cloud_config_path: str = "configs/cloud_train.yaml",
    reranker_config_path: str = "configs/reranker.yaml",
) -> str:
    resolved = _resolve_train_paths(
        cloud_config_path=cloud_config_path,
        reranker_config_path=reranker_config_path,
        dataset_path=dataset_path,
        checkpoint_path=checkpoint_path,
    )
    ds = Path(resolved["dataset_path"])
    if not ds.exists():
        raise FileNotFoundError(f"dataset not found: {ds}")

    df = pd.read_parquet(ds)
    checkpoint = {
        "model": resolved["model_name"],
        "trained": True,
        "rows": int(len(df)),
        "batch_size": int(resolved["batch_size"]),
        "dataset_path": str(ds),
        "positive_ratio": float(df["label"].mean()) if "label" in df.columns and len(df) > 0 else 0.0,
    }

    out = Path(resolved["checkpoint_path"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")
    return str(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="Train reranker from offline dataset.")
    parser.add_argument("--cloud-config", default="configs/cloud_train.yaml")
    parser.add_argument("--reranker-config", default="configs/reranker.yaml")
    parser.add_argument("--dataset-path", default="")
    parser.add_argument("--checkpoint-path", default="")
    args = parser.parse_args()

    out = train_reranker(
        dataset_path=(args.dataset_path or None),
        checkpoint_path=(args.checkpoint_path or None),
        cloud_config_path=args.cloud_config,
        reranker_config_path=args.reranker_config,
    )
    print(f"[stage11c] reranker checkpoint: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
