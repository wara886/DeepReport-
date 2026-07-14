"""Inspect or clean local runtime state without touching user or benchmark data."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any


EPHEMERAL_ROOTS = ("logs", "tmp", ".pytest_cache")
CONFIG_GLOBS = ("configs/*.yaml", "configs/*.yml", "pyproject.toml")
CREDENTIAL_NAMES = (
    "DEEPSEEK_API_KEY",
    "TAVILY_API_KEY",
    "SERPER_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
)


def build_baseline(repo_root: Path) -> dict[str, Any]:
    import os

    root = repo_root.resolve()
    return {
        "schema_version": "runtime_baseline.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repository": {
            "commit": _git(root, "rev-parse", "HEAD"),
            "branch": _git(root, "branch", "--show-current"),
            "dirty": bool(_git(root, "status", "--porcelain")),
        },
        "python": sys.version.split()[0],
        "configs": {
            str(path.relative_to(root)): _sha256(path)
            for pattern in CONFIG_GLOBS
            for path in sorted(root.glob(pattern))
            if path.is_file()
        },
        "credentials": {name: bool(os.getenv(name)) for name in CREDENTIAL_NAMES},
        "runtime_paths": {
            relative: _path_summary(root / relative)
            for relative in (*EPHEMERAL_ROOTS, "data/outputs_user", "data/reports_user", "data/vector_db")
        },
    }


def clean_ephemeral(repo_root: Path, *, apply: bool) -> list[str]:
    root = repo_root.resolve()
    targets = [root / relative for relative in EPHEMERAL_ROOTS]
    targets.extend(path for path in root.rglob("__pycache__") if ".git" not in path.parts)
    cleaned: list[str] = []
    for target in sorted(set(targets)):
        resolved = target.resolve()
        if root not in resolved.parents or not resolved.exists():
            continue
        cleaned.append(str(resolved.relative_to(root)))
        if apply:
            if resolved.is_dir():
                shutil.rmtree(resolved)
            else:
                resolved.unlink()
    return cleaned


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _path_summary(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "files": 0, "bytes": 0}
    files = [item for item in path.rglob("*") if item.is_file()]
    return {
        "exists": True,
        "files": len(files),
        "bytes": sum(item.stat().st_size for item in files),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status", "clean"))
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, help="Write the status manifest to this path")
    parser.add_argument("--apply", action="store_true", help="Actually delete ephemeral paths")
    args = parser.parse_args()

    if args.command == "status":
        payload = build_baseline(args.repo_root)
        encoded = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(encoded, encoding="utf-8")
        else:
            print(encoded, end="")
        return 0

    targets = clean_ephemeral(args.repo_root, apply=args.apply)
    action = "removed" if args.apply else "would remove"
    for target in targets:
        print(f"{action}: {target}")
    if not args.apply:
        print("Dry run only. Re-run with --apply to delete these ephemeral paths.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
