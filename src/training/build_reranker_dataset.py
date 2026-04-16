"""Build reranker training dataset from retrieval outputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

import pandas as pd

from src.utils.config import load_config


def _load_retrieval_results(path: str | Path = "data/outputs/retrieval_results.json") -> Dict[str, object]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"retrieval results not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def _resolve_reranker_paths(
    cloud_config_path: str,
    reranker_config_path: str,
    retrieval_path: str | Path | None,
    output_dir: str | Path | None,
) -> Dict[str, str]:
    cloud_cfg = load_config(cloud_config_path)
    reranker_cfg = load_config(reranker_config_path)
    del cloud_cfg  # Keep Stage 11C contract: cloud config is loaded for consistent source of truth.

    r_cfg = dict(reranker_cfg.get("reranker", {}))
    training_cfg = dict(r_cfg.get("training", {}))
    inference_cfg = dict(r_cfg.get("inference", {}))

    resolved_retrieval = str(retrieval_path or inference_cfg.get("input_path", "data/outputs/retrieval_results.json"))
    resolved_output_dir = str(output_dir or Path(str(training_cfg.get("dataset_path", "data/outputs/training/reranker/dataset.parquet"))).parent)
    return {
        "retrieval_path": resolved_retrieval,
        "output_dir": resolved_output_dir,
    }


def build_reranker_dataset(
    retrieval_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    cloud_config_path: str = "configs/cloud_train.yaml",
    reranker_config_path: str = "configs/reranker.yaml",
) -> Dict[str, str]:
    paths = _resolve_reranker_paths(
        cloud_config_path=cloud_config_path,
        reranker_config_path=reranker_config_path,
        retrieval_path=retrieval_path,
        output_dir=output_dir,
    )

    payload = _load_retrieval_results(paths["retrieval_path"])
    query = str(payload.get("query", ""))
    hits = list(payload.get("hits", []))

    rows: List[Dict[str, object]] = []
    for idx, hit in enumerate(hits):
        text = f"{hit.get('title', '')} {hit.get('content', '')}".strip()
        rows.append(
            {
                "query": query,
                "doc_id": hit.get("sample_id", f"doc_{idx:04d}"),
                "doc_text": text,
                "score": float(hit.get("score", 0.0)),
                "label": 1 if idx == 0 else 0,
            }
        )

    if not rows:
        rows.append({"query": query, "doc_id": "doc_empty", "doc_text": "", "score": 0.0, "label": 0})

    out_dir = Path(paths["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame(rows)
    parquet_path = out_dir / "dataset.parquet"
    jsonl_path = out_dir / "dataset.jsonl"
    df.to_parquet(parquet_path, index=False)
    with jsonl_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    return {
        "parquet": str(parquet_path),
        "jsonl": str(jsonl_path),
        "rows": str(len(rows)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build reranker dataset from offline retrieval outputs.")
    parser.add_argument("--cloud-config", default="configs/cloud_train.yaml")
    parser.add_argument("--reranker-config", default="configs/reranker.yaml")
    parser.add_argument("--retrieval-path", default="")
    parser.add_argument("--output-dir", default="")
    args = parser.parse_args()

    info = build_reranker_dataset(
        retrieval_path=(args.retrieval_path or None),
        output_dir=(args.output_dir or None),
        cloud_config_path=args.cloud_config,
        reranker_config_path=args.reranker_config,
    )
    print(f"[stage11c] reranker dataset parquet: {info['parquet']}")
    print(f"[stage11c] reranker dataset jsonl: {info['jsonl']}")
    print(f"[stage11c] reranker dataset rows: {info['rows']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
