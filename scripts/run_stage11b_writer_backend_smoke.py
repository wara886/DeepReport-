#!/usr/bin/env python3
"""Stage 11B smoke runner: real writer backend + fallback."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.app.pipeline import run_pipeline
from src.app.stage11a_real_data_pipeline import run_real_data_pipeline
from src.utils.config import load_config


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Stage 11B writer backend smoke.")
    parser.add_argument("--config", default="configs/local_real_smoke.yaml")
    args = parser.parse_args()

    config_path = args.config
    cfg = load_config(config_path)
    real_cfg = dict(cfg.get("real_data", {}))
    gen_cfg = dict(cfg.get("generation", {}))

    data_mode = str(real_cfg.get("data_mode", "local_file_real"))
    writer_mode = str(gen_cfg.get("writer_mode", "template_only"))
    writer_backend = str(gen_cfg.get("backend", "mock"))
    backend_config_path = str(gen_cfg.get("backend_config_path", "configs/model_backends.yaml"))

    if data_mode == "local_file_real":
        outputs = run_real_data_pipeline(config_path)
        report_md = Path(outputs["report_md"])
        writer_debug = Path(real_cfg.get("reports_root", "data/reports_real")) / "writer_debug.json"
    elif data_mode == "mock":
        paths_cfg = dict(cfg.get("paths", {}))
        output_root = str(paths_cfg.get("output_root", "data/outputs"))
        report_root = str(paths_cfg.get("report_root", "data/reports"))
        outputs = run_pipeline(
            output_dir=output_root,
            report_dir=report_root,
            features_root="data/features",
            writer_mode=writer_mode,
            writer_backend=writer_backend,
            writer_backend_config_path=backend_config_path,
            writer_debug_path=str(Path(report_root) / "writer_debug.json"),
        )
        report_md = Path(outputs["report_markdown"])
        writer_debug = Path(outputs["writer_debug"])
    else:
        raise ValueError(f"Unsupported data_mode: {data_mode}")

    print(f"[stage11b] data_mode: {data_mode}")
    print(f"[stage11b] writer_mode: {writer_mode}")
    print(f"[stage11b] writer_backend: {writer_backend}")
    print(f"[stage11b] report_md: {report_md}")
    print(f"[stage11b] writer_debug: {writer_debug}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
