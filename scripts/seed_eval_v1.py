"""Seed eval_v1 dataset from local raw data folders."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.eval_v1 import seed_eval_v1_cases, write_eval_cases, write_eval_schema


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed data/eval_v1/cases.jsonl")
    parser.add_argument("--raw-root", default="data/raw/real_data")
    parser.add_argument("--out-dir", default="data/eval_v1")
    parser.add_argument("--min-cases", type=int, default=30)
    args = parser.parse_args()

    cases = seed_eval_v1_cases(raw_root=args.raw_root, min_case_count=args.min_cases)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_eval_cases(out_dir / "cases.jsonl", cases)
    write_eval_schema(out_dir / "schema.json")
    print(f"[seed_eval_v1] raw_root={args.raw_root}")
    print(f"[seed_eval_v1] out_dir={out_dir}")
    print(f"[seed_eval_v1] cases={len(cases)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
