"""Run Phase 3 formal benchmark on a complete validated frozen snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.formal_benchmark import run_formal_benchmark  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the formal frozen FY2024 three-variant benchmark.")
    parser.add_argument("--config", default="configs/benchmark_formal18_fy2024.yaml")
    parser.add_argument("--snapshot-root", default="")
    parser.add_argument("--output-root", default="")
    parser.add_argument("--variants", nargs="*", default=[], help="Run only selected variants and merge with existing other-variant records when --reuse-existing is set.")
    parser.add_argument("--cases", nargs="*", default=[], help="Run only selected case IDs and preserve other current-snapshot records when --reuse-existing is set.")
    parser.add_argument("--reuse-existing", action="store_true", help="Reuse existing records for variants not selected, if they use the current snapshot hash.")
    args = parser.parse_args()
    result = run_formal_benchmark(
        config_path=args.config,
        snapshot_root=args.snapshot_root or None,
        output_root=args.output_root or None,
        variant_ids=args.variants or None,
        case_ids=args.cases or None,
        reuse_existing=args.reuse_existing,
    )
    print(
        json.dumps(
            {
                "case_count": result["case_count"],
                "report_count": result["report_count"],
                "report": result["paths"]["report"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
