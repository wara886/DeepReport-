"""Run official evidence backfill for an existing report outputs directory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.official_evidence_backfill import execute_official_evidence_backfill_for_run  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute official evidence backfill for a generated report run.")
    parser.add_argument("run_dir", help="Run directory or outputs directory containing run_summary.json.")
    parser.add_argument("--topk", type=int, default=10)
    args = parser.parse_args()

    result = execute_official_evidence_backfill_for_run(args.run_dir, topk=args.topk)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
