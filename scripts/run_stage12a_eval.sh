#!/usr/bin/env bash
set -euo pipefail

CONFIG_PATH="${1:-configs/evaluation_stage12a.yaml}"

echo "[stage12a] config=${CONFIG_PATH}"
python -m src.evaluation.stage12a_harness --config "${CONFIG_PATH}"
