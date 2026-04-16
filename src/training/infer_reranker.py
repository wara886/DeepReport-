"""Reranker inference with checkpoint fallback and mode metadata."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Tuple

from src.utils.config import load_config


def _load_checkpoint(path: str | Path) -> Dict[str, object] | None:
    p = Path(path)
    if not p.exists():
        return None
    return dict(json.loads(p.read_text(encoding="utf-8")))


def _resolve_infer_paths(
    cloud_config_path: str,
    reranker_config_path: str,
    input_path: str | None,
    checkpoint_path: str | None,
    output_path: str | None,
) -> Dict[str, str]:
    cloud_cfg = load_config(cloud_config_path)
    reranker_cfg = load_config(reranker_config_path)
    del cloud_cfg

    r_cfg = dict(reranker_cfg.get("reranker", {}))
    infer_cfg = dict(r_cfg.get("inference", {}))

    return {
        "input_path": str(input_path or infer_cfg.get("input_path", "data/outputs/retrieval_results.json")),
        "checkpoint_path": str(checkpoint_path or r_cfg.get("checkpoint_path", "data/outputs/checkpoints/reranker_checkpoint.json")),
        "output_path": str(output_path or infer_cfg.get("output_path", "data/outputs/reranked_results.json")),
    }


def rerank_hits_with_meta(
    hits: List[Dict[str, object]],
    checkpoint_path: str = "data/outputs/checkpoints/reranker_checkpoint.json",
) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    ckpt = _load_checkpoint(checkpoint_path)
    ranked: List[Dict[str, object]] = [dict(item) for item in hits]

    if ckpt:
        trust_weight = {"high": 0.2, "medium": 0.1, "low": 0.0}
        for item in ranked:
            base = float(item.get("score", 0.0))
            trust = trust_weight.get(str(item.get("trust_level", "medium")).lower(), 0.1)
            item["rerank_score"] = base + trust
        mode = "reranker"
        fallback_used = False
    else:
        for item in ranked:
            item["rerank_score"] = float(item.get("score", 0.0))
        mode = "bm25"
        fallback_used = True

    ranked.sort(key=lambda x: float(x.get("rerank_score", 0.0)), reverse=True)
    meta = {
        "mode": mode,
        "checkpoint_path": checkpoint_path,
        "checkpoint_used": bool(ckpt),
        "fallback_used": fallback_used,
    }
    return ranked, meta


def rerank_hits(
    hits: List[Dict[str, object]],
    checkpoint_path: str = "data/outputs/checkpoints/reranker_checkpoint.json",
) -> List[Dict[str, object]]:
    ranked, _ = rerank_hits_with_meta(hits=hits, checkpoint_path=checkpoint_path)
    return ranked


def main() -> int:
    parser = argparse.ArgumentParser(description="Run reranker inference with fallback.")
    parser.add_argument("--cloud-config", default="configs/cloud_train.yaml")
    parser.add_argument("--reranker-config", default="configs/reranker.yaml")
    parser.add_argument("--input-path", default="")
    parser.add_argument("--checkpoint-path", default="")
    parser.add_argument("--output-path", default="")
    args = parser.parse_args()

    resolved = _resolve_infer_paths(
        cloud_config_path=args.cloud_config,
        reranker_config_path=args.reranker_config,
        input_path=(args.input_path or None),
        checkpoint_path=(args.checkpoint_path or None),
        output_path=(args.output_path or None),
    )

    input_payload = json.loads(Path(resolved["input_path"]).read_text(encoding="utf-8"))
    hits = list(input_payload.get("hits", []))
    reranked, meta = rerank_hits_with_meta(hits, checkpoint_path=resolved["checkpoint_path"])

    out_payload = {"query": input_payload.get("query", ""), "hits": reranked, "meta": meta}
    out = Path(resolved["output_path"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(out_payload, indent=2), encoding="utf-8")
    print(f"[stage11c] reranked output: {out}")
    print(f"[stage11c] ranking mode: {meta['mode']} fallback={meta['fallback_used']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
