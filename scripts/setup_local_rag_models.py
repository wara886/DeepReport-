"""Install or warm up local embedding/reranker models for the financial agent."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.config import load_config


def main() -> int:
    parser = argparse.ArgumentParser(description="Warm up local RAG models into the local cache.")
    parser.add_argument("--config-path", default="configs/local_rag.yaml")
    parser.add_argument("--embedding-model", default="")
    parser.add_argument("--reranker-model", default="")
    parser.add_argument("--source", choices=["hf", "hf-mirror", "modelscope"], default="hf")
    parser.add_argument("--no-proxy", action="store_true", help="Unset HTTP(S)/SOCKS proxy env vars for this process.")
    parser.add_argument("--skip-embedding", action="store_true")
    parser.add_argument("--skip-reranker", action="store_true")
    args = parser.parse_args()

    cfg = load_config(args.config_path)
    rag_cfg = dict(cfg.get("local_rag", {}))
    local_model_root = PROJECT_ROOT / "models"
    if args.no_proxy:
        _clear_proxy_env()
    if args.source == "hf-mirror":
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    if args.source in {"hf", "hf-mirror"}:
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    os.environ.setdefault("HF_HOME", str(local_model_root / "huggingface"))
    os.environ.setdefault("TRANSFORMERS_CACHE", str(local_model_root / "huggingface" / "transformers"))
    os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", str(local_model_root / "sentence_transformers"))
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    embedding_model = str(args.embedding_model or rag_cfg.get("embedding_model_name", "BAAI/bge-small-en-v1.5"))
    reranker_model = str(args.reranker_model or rag_cfg.get("reranker_model_name", "BAAI/bge-reranker-base"))

    try:
        from sentence_transformers import CrossEncoder, SentenceTransformer  # type: ignore
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "sentence-transformers is not installed",
                    "hint": "Run: pip install '.[local_rag]'",
                    "details": str(exc),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    payload = {
        "ok": True,
        "config_path": args.config_path,
        "model_cache_root": str(local_model_root),
        "source": args.source,
        "proxy_disabled": bool(args.no_proxy),
        "embedding_model": embedding_model,
        "reranker_model": reranker_model,
        "embedding_ready": False,
        "reranker_ready": False,
    }

    if args.source == "modelscope":
        if not args.skip_embedding:
            _download_from_modelscope(embedding_model, local_model_root)
            payload["embedding_ready"] = True
        if not args.skip_reranker:
            local_path = _download_from_modelscope(reranker_model, local_model_root)
            model = CrossEncoder(str(local_path))
            model.predict([["financial report", "warmup pair"]])
            payload["reranker_ready"] = True
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if not args.skip_embedding:
        model = SentenceTransformer(embedding_model)
        model.encode(["financial agent warmup"], normalize_embeddings=True)
        payload["embedding_ready"] = True

    if not args.skip_reranker:
        model = CrossEncoder(reranker_model)
        model.predict([["financial report", "warmup pair"]])
        payload["reranker_ready"] = True

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _clear_proxy_env() -> None:
    for key in [
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "NO_PROXY",
        "no_proxy",
    ]:
        os.environ.pop(key, None)


def _download_from_modelscope(model_id: str, local_model_root: Path) -> Path:
    try:
        from modelscope import snapshot_download  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "modelscope is not installed. Run: .\\.venv\\Scripts\\python.exe -m pip install modelscope"
        ) from exc

    cache_dir = local_model_root / "modelscope"
    cache_dir.mkdir(parents=True, exist_ok=True)
    local_path = snapshot_download(model_id, cache_dir=str(cache_dir))
    return Path(local_path)


if __name__ == "__main__":
    raise SystemExit(main())
