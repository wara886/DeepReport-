"""Smoke test for Tavily Search integration."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.search.search_manager import tavily_search


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a minimal Tavily search smoke test.")
    parser.add_argument("--query", default="AAPL latest quarterly financial results revenue cash flow")
    parser.add_argument("--topk", type=int, default=3)
    args = parser.parse_args()

    payload = tavily_search(query=args.query, topk=args.topk)
    preview = {
        "mode": payload["meta"].get("mode"),
        "result_count": len(payload.get("hits", [])),
        "request_id_present": bool(payload["meta"].get("request_id")),
        "results": [
            {
                "title": item.get("title", ""),
                "url": item.get("source_url", ""),
                "score": item.get("score", 0.0),
            }
            for item in payload.get("hits", [])
        ],
    }
    print(json.dumps(preview, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
