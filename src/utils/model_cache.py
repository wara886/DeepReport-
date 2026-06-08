"""Local model cache helpers for retrieval and reranker runtimes."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml


_RETRIEVAL_CONFIG_CACHE: Dict[str, Any] | None = None


def ensure_model_cache_env(config: Dict[str, Any] | None = None) -> Path:
    """Pin Hugging Face/SentenceTransformers cache paths inside the project."""

    cfg = config if isinstance(config, dict) else _load_retrieval_config()
    retrieval = cfg.get("retrieval", cfg) if isinstance(cfg, dict) else {}
    raw_root = ""
    if isinstance(retrieval, dict):
        raw_root = str(retrieval.get("model_cache_root") or "")
    repo_root = Path(__file__).resolve().parents[2]
    cache_root = Path(raw_root or "models")
    if not cache_root.is_absolute():
        cache_root = repo_root / cache_root
    hf_home = cache_root / "huggingface"
    st_home = cache_root / "sentence_transformers"
    transformers_cache = hf_home / "transformers"
    for path in [hf_home, st_home, transformers_cache]:
        path.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(hf_home))
    os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", str(st_home))
    os.environ.setdefault("TRANSFORMERS_CACHE", str(transformers_cache))
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    return cache_root


def embedding_local_files_only() -> bool:
    cfg = _load_retrieval_config()
    retrieval = cfg.get("retrieval", cfg) if isinstance(cfg, dict) else {}
    if isinstance(retrieval, dict):
        value = retrieval.get("local_files_only")
        if value is not None:
            return bool(value)
        router = retrieval.get("embedding_router")
        if isinstance(router, dict) and router.get("local_files_only") is not None:
            return bool(router.get("local_files_only"))
    return False


def _load_retrieval_config() -> Dict[str, Any]:
    global _RETRIEVAL_CONFIG_CACHE
    if _RETRIEVAL_CONFIG_CACHE is not None:
        return _RETRIEVAL_CONFIG_CACHE
    repo_root = Path(__file__).resolve().parents[2]
    for path in [Path("configs/retrieval.yaml"), repo_root / "configs" / "retrieval.yaml"]:
        try:
            if path.exists():
                with path.open("r", encoding="utf-8") as fh:
                    payload = yaml.safe_load(fh) or {}
                _RETRIEVAL_CONFIG_CACHE = dict(payload) if isinstance(payload, dict) else {}
                return _RETRIEVAL_CONFIG_CACHE
        except Exception:
            continue
    _RETRIEVAL_CONFIG_CACHE = {}
    return _RETRIEVAL_CONFIG_CACHE
