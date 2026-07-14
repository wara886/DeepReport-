"""Local model cache helpers for retrieval and reranker runtimes."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml

from src.utils.env import load_env_files


_RETRIEVAL_CONFIG_CACHE: Dict[str, Any] | None = None


def ensure_model_cache_env(config: Dict[str, Any] | None = None) -> Path:
    """Pin Hugging Face/SentenceTransformers cache paths inside the project."""

    repo_root = Path(__file__).resolve().parents[2]
    load_env_files(config_path=repo_root / "configs" / "retrieval.yaml")
    cfg = config if isinstance(config, dict) else _load_retrieval_config()
    retrieval = cfg.get("retrieval", cfg) if isinstance(cfg, dict) else {}
    raw_root = ""
    if isinstance(retrieval, dict):
        raw_root = str(retrieval.get("model_cache_root") or "")
    env_root = str(os.getenv("FINSIGHT_MODEL_CACHE_ROOT") or "").strip()
    cache_root = Path(env_root or raw_root or "models").expanduser()
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


def resolve_local_model_path(model_name: str, *, category: str | None = None) -> str:
    """Resolve a configured model id to a complete local model directory.

    Local model bundles in this project are not always stored in Hugging Face's
    cache layout. Rerankers, for example, may live under ``models/rerankers``.
    Returning the original id keeps the standard Hugging Face lookup behavior
    when no complete local bundle is available.
    """

    text = str(model_name or "").strip()
    if not text:
        return text
    direct = Path(text).expanduser()
    if direct.is_dir() and _is_model_directory(direct):
        return str(direct.resolve())

    cache_root = ensure_model_cache_env()
    leaf = text.rsplit("/", 1)[-1]
    candidates = []
    if category:
        candidates.append(cache_root / category / leaf)
    candidates.extend(
        [
            cache_root / "rerankers" / leaf,
            cache_root / "models" / leaf,
            cache_root / leaf,
        ]
    )
    for candidate in candidates:
        if candidate.is_dir() and _is_model_directory(candidate):
            return str(candidate.resolve())
    return text


def _is_model_directory(path: Path) -> bool:
    return (path / "config.json").is_file() and any(
        (path / filename).is_file()
        for filename in ("model.safetensors", "pytorch_model.bin", "tf_model.h5")
    )


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
