"""Acquire period-verified public evidence for the formal FY2024 snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.formal_evidence_staging import stage_formal_evidence  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage explicitly acquired FY2024 formal benchmark evidence.")
    parser.add_argument("--config", default="configs/benchmark_formal18_fy2024.yaml")
    parser.add_argument("--data-source-config", default="configs/data_sources.yaml")
    parser.add_argument("--source-root", default="")
    parser.add_argument("--markets", nargs="*", default=[])
    args = parser.parse_args()
    manifest = stage_formal_evidence(
        config_path=args.config,
        source_root=args.source_root or None,
        data_source_config_path=args.data_source_config,
        markets=args.markets or None,
    )
    print(
        json.dumps(
            {
                "period": manifest["period"],
                "staged_cases": f"{manifest['staged_case_count']}/{manifest['case_count']}",
                "blocked_cases": manifest["blocked_case_count"],
                "manifest": str(Path(manifest["source_root"]) / "acquisition_manifest.json"),
            },
            ensure_ascii=False,
        )
    )
    return 0 if manifest["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
