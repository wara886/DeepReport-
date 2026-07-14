"""Deterministic project-local .env loader shared by runtime adapters."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List


def load_env_files(config_path: str | Path | None = None, env_path: str | Path | None = None) -> None:
    """Load explicit and project-local env files without crossing repository boundaries.

    Existing process variables always win.  This lets tests and deployments
    explicitly disable a credential by setting it to an empty string.
    """

    candidates: List[Path] = []
    if env_path:
        candidates.append(Path(env_path))
    if config_path:
        path = Path(config_path).resolve()
        if path.parent.name == "configs":
            candidates.append(path.parent.parent / ".env")
    candidates.append(Path.cwd() / ".env")

    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.exists():
            load_env_file(resolved)


def load_env_file(path: str | Path) -> None:
    path = Path(path)
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = strip_env_value(value.strip())
        if key and key not in os.environ:
            os.environ[key] = value


def strip_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def resolve_config_value(config: Dict[str, Any], key: str, default: Any) -> Any:
    env_key = config.get(f"{key}_env")
    if env_key:
        env_value = os.environ.get(str(env_key))
        if env_value not in (None, ""):
            return env_value
    value = config.get(key, default)
    return default if value in (None, "") else value
