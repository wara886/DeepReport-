#!/usr/bin/env python3
"""Stage 7 smoke runner for BM25 retrieval."""

from __future__ import annotations

import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.retrieval.retrieve import retrieve_evidence


def main() -> int:
    query = "revenue gross margin risk"
    hits = retrieve_evidence(query=query, topk=5)

    out_path = Path("data/outputs/retrieval_results.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"query": query, "hits": hits}, indent=2), encoding="utf-8")

    print(f"[stage7] query: {query}")
    print(f"[stage7] hits: {len(hits)}")
    print(f"[stage7] output: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

