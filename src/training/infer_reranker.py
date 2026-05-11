"""Reranker inference with optional local cross-encoder and heuristic fallback."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Tuple

from src.data.source_quality import grade_source
from src.utils.config import load_config


_CROSS_ENCODER_CACHE: Dict[str, object] = {}


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
    query: str = "",
    checkpoint_path: str = "data/outputs/checkpoints/reranker_checkpoint.json",
) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    ckpt = _load_checkpoint(checkpoint_path)
    ranked: List[Dict[str, object]] = [dict(item) for item in hits]
    model_name = str((ckpt or {}).get("model_name") or (ckpt or {}).get("model") or "BAAI/bge-reranker-base")

    if ckpt and query.strip():
        cross_encoder = _load_cross_encoder(model_name)
        if cross_encoder is not None:
            pairs = [[query, _hit_text(item)] for item in ranked]
            scores = cross_encoder.predict(pairs)
            for item, score in zip(ranked, scores):
                item["rerank_score"] = float(score)
            ranked.sort(key=lambda x: float(x.get("rerank_score", 0.0)), reverse=True)
            meta = {
                "mode": "reranker",
                "backend": "cross_encoder",
                "model_name": model_name,
                "checkpoint_path": checkpoint_path,
                "checkpoint_used": True,
                "fallback_used": False,
                "score_components": ["cross_encoder"],
            }
            return ranked, meta

    if ckpt:
        feature_weights = _feature_weights_from_checkpoint(ckpt)
        _apply_financial_heuristic_rerank(ranked, query=query, feature_weights=feature_weights)
        mode = "reranker"
        fallback_used = False
        backend = "financial_heuristic"
    else:
        for item in ranked:
            item["rerank_score"] = float(item.get("score", 0.0))
        mode = "bm25"
        fallback_used = True
        backend = "score_passthrough"

    ranked.sort(key=lambda x: float(x.get("rerank_score", 0.0)), reverse=True)
    meta = {
        "mode": mode,
        "backend": backend,
        "model_name": model_name,
        "checkpoint_path": checkpoint_path,
        "checkpoint_used": bool(ckpt),
        "fallback_used": fallback_used,
        "score_components": ["base_score"] if not ckpt else [
            "base_score",
            "query_overlap",
            "numeric_match",
            "source_authority",
            "freshness",
            "chunk_type",
        ],
        "feature_weights": _feature_weights_from_checkpoint(ckpt) if ckpt else {},
    }
    return ranked, meta


def rerank_hits(
    hits: List[Dict[str, object]],
    query: str = "",
    checkpoint_path: str = "data/outputs/checkpoints/reranker_checkpoint.json",
) -> List[Dict[str, object]]:
    ranked, _ = rerank_hits_with_meta(hits=hits, query=query, checkpoint_path=checkpoint_path)
    return ranked


def _load_cross_encoder(model_name: str) -> object | None:
    if model_name in _CROSS_ENCODER_CACHE:
        cached = _CROSS_ENCODER_CACHE[model_name]
        return cached if cached is not False else None
    try:
        from sentence_transformers import CrossEncoder  # type: ignore

        model = CrossEncoder(model_name)
        _CROSS_ENCODER_CACHE[model_name] = model
        return model
    except Exception:
        _CROSS_ENCODER_CACHE[model_name] = False
        return None


def _apply_financial_heuristic_rerank(
    ranked: List[Dict[str, object]],
    query: str = "",
    feature_weights: Dict[str, float] | None = None,
) -> None:
    weights = _default_feature_weights()
    if feature_weights:
        weights.update({key: float(value) for key, value in feature_weights.items() if key in weights})
    query_terms = _tokens(query)
    query_numbers = _numbers(query)
    for item in ranked:
        base = float(item.get("hybrid_score", item.get("score", 0.0)) or 0.0)
        text = _hit_text(item)
        overlap = _overlap_score(query_terms=query_terms, text_terms=_tokens(text))
        numeric = _numeric_match_score(query_numbers=query_numbers, item=item, text=text)
        authority = _authority_score(item)
        freshness = _freshness_score(item.get("publish_time", ""))
        chunk = _chunk_type_score(item)
        item["rerank_score"] = (
            base * weights["base_score"]
            + overlap * weights["query_overlap"]
            + numeric * weights["numeric_match"]
            + authority * weights["source_authority"]
            + freshness * weights["freshness"]
            + chunk * weights["chunk_type"]
        )
        item["rerank_components"] = {
            "base_score": round(base, 6),
            "query_overlap": round(overlap, 6),
            "numeric_match": round(numeric, 6),
            "source_authority": round(authority, 6),
            "freshness": round(freshness, 6),
            "chunk_type": round(chunk, 6),
        }


def _default_feature_weights() -> Dict[str, float]:
    return {
        "base_score": 1.0,
        "query_overlap": 0.9,
        "numeric_match": 0.45,
        "source_authority": 0.35,
        "freshness": 0.1,
        "chunk_type": 0.12,
    }


def _feature_weights_from_checkpoint(ckpt: Dict[str, object] | None) -> Dict[str, float]:
    raw = (ckpt or {}).get("feature_weights", {})
    if not isinstance(raw, dict):
        return {}
    output: Dict[str, float] = {}
    for key, value in raw.items():
        try:
            output[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return output


def _hit_text(item: Dict[str, object]) -> str:
    title = str(item.get("title", ""))
    content = str(item.get("content", ""))
    source_type = str(item.get("source_type", ""))
    return f"{title}\n{source_type}\n{content[:1800]}".strip()


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in re.findall(r"[A-Za-z0-9_.%]+", str(text or "")) if len(token) > 1}


def _numbers(text: str) -> set[str]:
    return {match.group(0).rstrip("0").rstrip(".") for match in re.finditer(r"-?\d+(?:\.\d+)?", str(text or ""))}


def _overlap_score(query_terms: set[str], text_terms: set[str]) -> float:
    if not query_terms or not text_terms:
        return 0.0
    return len(query_terms & text_terms) / max(len(query_terms), 1)


def _numeric_match_score(query_numbers: set[str], item: Dict[str, object], text: str) -> float:
    item_numbers = _numbers(text)
    numeric_values = item.get("numeric_values", {})
    if isinstance(numeric_values, dict):
        item_numbers.update(_normalize_number(value) for value in numeric_values.values())
    item_numbers = {value for value in item_numbers if value}
    if not query_numbers:
        return 0.2 if item_numbers else 0.0
    return len(query_numbers & item_numbers) / max(len(query_numbers), 1)


def _authority_score(item: Dict[str, object]) -> float:
    authority = item.get("authority_score")
    try:
        if authority not in {None, ""}:
            return float(authority)
    except (TypeError, ValueError):
        pass
    grade = grade_source(dict(item))
    return float(grade.get("authority_score", 0.35) or 0.35)


def _freshness_score(value: Any) -> float:
    text = str(value or "")
    year_match = re.search(r"(20\d{2})", text)
    if not year_match:
        return 0.0
    year = int(year_match.group(1))
    return max(0.0, min(1.0, (year - 2020) / 6.0))


def _chunk_type_score(item: Dict[str, object]) -> float:
    chunk_type = str(item.get("chunk_type", "")).lower()
    source_type = str(item.get("source_type", "")).lower()
    if chunk_type == "metric":
        return 1.0
    if chunk_type == "table_row":
        return 0.85
    if source_type in {"financials", "filing", "market_api"}:
        return 0.55
    if chunk_type == "paragraph":
        return 0.35
    return 0.0


def _normalize_number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{number:g}"


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
    reranked, meta = rerank_hits_with_meta(
        hits,
        query=str(input_payload.get("query", "")),
        checkpoint_path=resolved["checkpoint_path"],
    )

    out_payload = {"query": input_payload.get("query", ""), "hits": reranked, "meta": meta}
    out = Path(resolved["output_path"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(out_payload, indent=2), encoding="utf-8")
    print(f"[stage11c] reranked output: {out}")
    print(f"[stage11c] ranking mode: {meta['mode']} fallback={meta['fallback_used']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
