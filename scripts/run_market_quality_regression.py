"""Run the small P1 multi-market report-quality regression suite."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.market_quality_regression import run_market_quality_regression, run_real_artifact_quality_regression  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run P1 multi-market report quality regression.")
    parser.add_argument("--output-root", default="data/evaluation/p1_market_quality_regression")
    parser.add_argument("--fail-under", type=float, default=0.0, help="Return non-zero if delivery pass rate is below this value.")
    parser.add_argument("--real-artifacts", action="store_true", help="Re-score existing generated report artifacts instead of synthetic fixed samples.")
    parser.add_argument("--source-root", action="append", default=[], help="Artifact root to scan; can be passed multiple times.")
    parser.add_argument("--max-per-market", type=int, default=2)
    args = parser.parse_args()

    if args.real_artifacts:
        result = run_real_artifact_quality_regression(
            output_root=args.output_root,
            source_roots=args.source_root or None,
            max_per_market=args.max_per_market,
        )
    else:
        result = run_market_quality_regression(output_root=args.output_root)
    pass_rate = result["summary"]["overall"]["delivery_pass_rate"]
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if pass_rate is not None and pass_rate < args.fail_under:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
