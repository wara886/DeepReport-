#!/usr/bin/env python3
"""Stage 8 smoke runner for offline training dataset export."""

from __future__ import annotations

import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.training.build_reranker_dataset import build_reranker_dataset
from src.training.build_rewriter_dataset import build_rewriter_dataset
from src.training.build_verifier_dataset import build_verifier_dataset


def main() -> int:
    reranker = build_reranker_dataset()
    rewriter = build_rewriter_dataset()
    verifier = build_verifier_dataset()

    report = {
        "reranker": reranker,
        "rewriter": rewriter,
        "verifier": verifier,
    }

    out = Path("data/outputs/training/dataset_report.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"[stage8] report: {out}")
    print(f"[stage8] reranker rows: {reranker['rows']}")
    print(f"[stage8] rewriter rows: {rewriter['rows']}")
    print(f"[stage8] verifier rows: {verifier['rows']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

