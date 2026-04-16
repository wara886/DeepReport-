#!/usr/bin/env bash
set -euo pipefail

# Stage 11C: minimal reranker cloud-train validation chain.

CLOUD_CONFIG="${CLOUD_CONFIG:-configs/cloud_train.yaml}"
RERANKER_CONFIG="${RERANKER_CONFIG:-configs/reranker.yaml}"
LOCAL_SIMULATION="${LOCAL_SIMULATION:-1}"
DRY_RUN="${DRY_RUN:-0}"

REMOTE_HOST="${REMOTE_HOST:-}"
REMOTE_PORT="${REMOTE_PORT:-22}"
REMOTE_USER="${REMOTE_USER:-}"
REMOTE_BASE_DIR="${REMOTE_BASE_DIR:-data/simulated_remote}"
LOCAL_EXPORT_DIR="${LOCAL_EXPORT_DIR:-data/outputs/training/reranker}"
LOCAL_CHECKPOINT_DIR="${LOCAL_CHECKPOINT_DIR:-data/outputs/checkpoints}"
TRANSFER_LOG_PATH="${TRANSFER_LOG_PATH:-data/outputs/transfer_debug.log}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cloud-config) CLOUD_CONFIG="$2"; shift 2 ;;
    --reranker-config) RERANKER_CONFIG="$2"; shift 2 ;;
    --remote-host) REMOTE_HOST="$2"; shift 2 ;;
    --remote-port) REMOTE_PORT="$2"; shift 2 ;;
    --remote-user) REMOTE_USER="$2"; shift 2 ;;
    --remote-base-dir) REMOTE_BASE_DIR="$2"; shift 2 ;;
    --local-export-dir) LOCAL_EXPORT_DIR="$2"; shift 2 ;;
    --local-checkpoint-dir) LOCAL_CHECKPOINT_DIR="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift 1 ;;
    --local-simulation) LOCAL_SIMULATION=1; shift 1 ;;
    --remote-real) LOCAL_SIMULATION=0; shift 1 ;;
    --log-path) TRANSFER_LOG_PATH="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 2 ;;
  esac
done

echo "[stage11c] step1: build reranker dataset"
python -m src.training.build_reranker_dataset \
  --cloud-config "${CLOUD_CONFIG}" \
  --reranker-config "${RERANKER_CONFIG}"

echo "[stage11c] step2: upload offline export"
bash scripts/upload_to_cloud.sh \
  --remote-host "${REMOTE_HOST}" \
  --remote-port "${REMOTE_PORT}" \
  --remote-user "${REMOTE_USER}" \
  --remote-base-dir "${REMOTE_BASE_DIR}" \
  --local-export-dir "${LOCAL_EXPORT_DIR}" \
  --local-checkpoint-dir "${LOCAL_CHECKPOINT_DIR}" \
  --log-path "${TRANSFER_LOG_PATH}" \
  $( [[ "${LOCAL_SIMULATION}" == "1" ]] && echo "--local-simulation" ) \
  $( [[ "${DRY_RUN}" == "1" ]] && echo "--dry-run" )

REMOTE_DATASET_PATH="${REMOTE_BASE_DIR}/exports/reranker/dataset.parquet"
REMOTE_CHECKPOINT_PATH="${REMOTE_BASE_DIR}/checkpoints/reranker_checkpoint.json"

if [[ "${DRY_RUN}" == "1" ]]; then
  echo "[stage11c] step3: DRY_RUN remote train command"
  echo "python -m src.training.train_reranker --cloud-config ${CLOUD_CONFIG} --reranker-config ${RERANKER_CONFIG} --dataset-path ${REMOTE_DATASET_PATH} --checkpoint-path ${REMOTE_CHECKPOINT_PATH}"
else
  echo "[stage11c] step3: train reranker"
  if [[ "${LOCAL_SIMULATION}" == "1" ]]; then
    python -m src.training.train_reranker \
      --cloud-config "${CLOUD_CONFIG}" \
      --reranker-config "${RERANKER_CONFIG}" \
      --dataset-path "${REMOTE_DATASET_PATH}" \
      --checkpoint-path "${REMOTE_CHECKPOINT_PATH}"
  else
    if [[ -z "${REMOTE_HOST}" || -z "${REMOTE_USER}" ]]; then
      echo "[stage11c] ERROR: REMOTE_HOST and REMOTE_USER required for remote mode."
      exit 2
    fi
    SSH_TARGET="${REMOTE_USER}@${REMOTE_HOST}"
    TRAIN_CMD="cd ${REMOTE_BASE_DIR} && python -m src.training.train_reranker --cloud-config ${CLOUD_CONFIG} --reranker-config ${RERANKER_CONFIG} --dataset-path ${REMOTE_DATASET_PATH} --checkpoint-path ${REMOTE_CHECKPOINT_PATH}"
    ssh -p "${REMOTE_PORT}" "${SSH_TARGET}" "${TRAIN_CMD}"
  fi
fi

echo "[stage11c] step4: download checkpoint"
bash scripts/download_from_cloud.sh \
  --remote-host "${REMOTE_HOST}" \
  --remote-port "${REMOTE_PORT}" \
  --remote-user "${REMOTE_USER}" \
  --remote-base-dir "${REMOTE_BASE_DIR}" \
  --local-export-dir "${LOCAL_EXPORT_DIR}" \
  --local-checkpoint-dir "${LOCAL_CHECKPOINT_DIR}" \
  --log-path "${TRANSFER_LOG_PATH}" \
  $( [[ "${LOCAL_SIMULATION}" == "1" ]] && echo "--local-simulation" ) \
  $( [[ "${DRY_RUN}" == "1" ]] && echo "--dry-run" )

if [[ "${DRY_RUN}" == "1" ]]; then
  echo "[stage11c] step5: DRY_RUN infer command"
  echo "python -m src.training.infer_reranker --cloud-config ${CLOUD_CONFIG} --reranker-config ${RERANKER_CONFIG}"
  exit 0
fi

echo "[stage11c] step5: local reranker infer"
python -m src.training.infer_reranker \
  --cloud-config "${CLOUD_CONFIG}" \
  --reranker-config "${RERANKER_CONFIG}"

echo "[stage11c] done: output data/outputs/reranked_results.json"
