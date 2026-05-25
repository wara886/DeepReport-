"""Build the formal FY2024 frozen evidence snapshot from staged local files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.frozen_snapshot import build_frozen_snapshot  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Freeze pre-staged FY2024 evidence without any network fetching.")
    parser.add_argument("--config", default="configs/benchmark_formal18_fy2024.yaml")
    parser.add_argument("--source-root", default="")
    parser.add_argument("--snapshot-root", default="")
    args = parser.parse_args()
    manifest = build_frozen_snapshot(
        config_path=args.config,
        source_root=args.source_root or None,
        snapshot_root=args.snapshot_root or None,
    )
    print(
        json.dumps(
            {
                "dataset_version": manifest["dataset_version"],
                "ready_cases": f"{manifest['ready_case_count']}/{manifest['case_count']}",
                "complete": manifest["complete"],
                "manifest": str(Path(manifest["snapshot_root"]) / "snapshot_manifest.json"),
            },
            ensure_ascii=False,
        )
    )
    return 0 if manifest["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
