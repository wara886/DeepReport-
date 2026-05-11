"""Offline reranker training entry for Stage 11C."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any, Dict, List

import pandas as pd

from src.data.source_quality import grade_source
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
    feature_weights = _calibrate_feature_weights(df)
    checkpoint = {
        "model": resolved["model_name"],
        "model_name": resolved["model_name"],
        "trained": True,
        "training_mode": "feature_calibrated_heuristic",
        "rows": int(len(df)),
        "batch_size": int(resolved["batch_size"]),
        "dataset_path": str(ds),
        "positive_ratio": float(df["label"].mean()) if "label" in df.columns and len(df) > 0 else 0.0,
        "feature_weights": feature_weights,
        "feature_names": sorted(feature_weights),
    }

    out = Path(resolved["checkpoint_path"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")
    return str(out)


def _calibrate_feature_weights(df: pd.DataFrame) -> Dict[str, float]:
    """Estimate small reranker weights from positives vs hard negatives."""

    defaults = {
        "base_score": 1.0,
        "query_overlap": 0.9,
        "numeric_match": 0.45,
        "source_authority": 0.35,
        "freshness": 0.1,
        "chunk_type": 0.12,
    }
    if df.empty or "label" not in df.columns:
        return defaults

    rows = [_feature_row(dict(row)) for row in df.to_dict(orient="records")]
    feature_names = list(defaults)
    labels = [float(row.get("label", 0.0) or 0.0) for row in rows]
    positives = [row for row, label in zip(rows, labels) if label >= 0.5]
    negatives = [row for row, label in zip(rows, labels) if label < 0.5]
    if not positives or not negatives:
        return defaults

    weights: Dict[str, float] = {}
    for name in feature_names:
        pos_mean = _mean([float(row.get(name, 0.0) or 0.0) for row in positives])
        neg_mean = _mean([float(row.get(name, 0.0) or 0.0) for row in negatives])
        delta = max(0.0, pos_mean - neg_mean)
        weights[name] = round(defaults[name] + delta, 4)
    return weights


def _feature_row(row: Dict[str, Any]) -> Dict[str, float]:
    query = str(row.get("query", ""))
    text = str(row.get("doc_text", ""))
    source_type = str(row.get("source_type", ""))
    record = {
        "source_type": source_type,
        "source_url": str(row.get("source_url", "")),
        "trust_level": str(row.get("trust_level", "")),
        "publish_time": str(row.get("publish_time", "")),
        "chunk_type": str(row.get("chunk_type", "")),
    }
    return {
        "base_score": float(row.get("score", 0.0) or 0.0),
        "query_overlap": _overlap_score(_tokens(query), _tokens(text)),
        "numeric_match": _numeric_match_score(_numbers(query), _numbers(text)),
        "source_authority": float(grade_source(record).get("authority_score", 0.35) or 0.35),
        "freshness": _freshness_score(str(row.get("publish_time", ""))),
        "chunk_type": _chunk_type_score(source_type=source_type, chunk_type=str(row.get("chunk_type", ""))),
        "label": float(row.get("label", 0.0) or 0.0),
    }


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in re.findall(r"[A-Za-z0-9_.%]+", str(text or "")) if len(token) > 1}


def _numbers(text: str) -> set[str]:
    return {match.group(0).rstrip("0").rstrip(".") for match in re.finditer(r"-?\d+(?:\.\d+)?", str(text or ""))}


def _overlap_score(query_terms: set[str], text_terms: set[str]) -> float:
    if not query_terms or not text_terms:
        return 0.0
    return len(query_terms & text_terms) / max(len(query_terms), 1)


def _numeric_match_score(query_numbers: set[str], doc_numbers: set[str]) -> float:
    doc_numbers = {value for value in doc_numbers if value}
    if not query_numbers:
        return 0.2 if doc_numbers else 0.0
    return len(query_numbers & doc_numbers) / max(len(query_numbers), 1)


def _freshness_score(value: str) -> float:
    year_match = re.search(r"(20\d{2})", str(value or ""))
    if not year_match:
        return 0.0
    year = int(year_match.group(1))
    return max(0.0, min(1.0, (year - 2020) / 6.0))


def _chunk_type_score(source_type: str, chunk_type: str) -> float:
    chunk = chunk_type.lower()
    source = source_type.lower()
    if chunk == "metric":
        return 1.0
    if chunk == "table_row":
        return 0.85
    if source in {"financials", "filing", "market_api"}:
        return 0.55
    if chunk == "paragraph":
        return 0.35
    return 0.0


def _mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


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
