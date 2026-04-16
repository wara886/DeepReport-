#!/usr/bin/env python3
"""Minimal local smoke entry for Stage 0."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.utils.config import load_config


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local smoke check.")
    parser.add_argument(
        "--config",
        default="configs/local_smoke.yaml",
        help="Path to YAML config file.",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    runtime_mode = config.get("runtime", {}).get("mode", "unknown")
    backend = config.get("generation", {}).get("backend", "unknown")
    out_root = config.get("paths", {}).get("output_root", "data/outputs")

    Path(out_root).mkdir(parents=True, exist_ok=True)
    print(f"[smoke] runtime.mode={runtime_mode}")
    print(f"[smoke] generation.backend={backend}")
    print(f"[smoke] output_root={out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
