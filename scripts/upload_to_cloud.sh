#!/usr/bin/env bash
set -euo pipefail

# Stage 11C: upload offline reranker export to cloud/local-sim workspace.

REMOTE_HOST="${REMOTE_HOST:-}"
REMOTE_PORT="${REMOTE_PORT:-22}"
REMOTE_USER="${REMOTE_USER:-}"
REMOTE_BASE_DIR="${REMOTE_BASE_DIR:-}"
LOCAL_EXPORT_DIR="${LOCAL_EXPORT_DIR:-data/outputs/training/reranker}"
LOCAL_CHECKPOINT_DIR="${LOCAL_CHECKPOINT_DIR:-data/outputs/checkpoints}"
DRY_RUN="${DRY_RUN:-0}"
LOCAL_SIMULATION="${LOCAL_SIMULATION:-0}"
TRANSFER_LOG_PATH="${TRANSFER_LOG_PATH:-data/outputs/transfer_debug.log}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --remote-host) REMOTE_HOST="$2"; shift 2 ;;
    --remote-port) REMOTE_PORT="$2"; shift 2 ;;
    --remote-user) REMOTE_USER="$2"; shift 2 ;;
    --remote-base-dir) REMOTE_BASE_DIR="$2"; shift 2 ;;
    --local-export-dir) LOCAL_EXPORT_DIR="$2"; shift 2 ;;
    --local-checkpoint-dir) LOCAL_CHECKPOINT_DIR="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift 1 ;;
    --local-simulation) LOCAL_SIMULATION=1; shift 1 ;;
    --log-path) TRANSFER_LOG_PATH="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 2 ;;
  esac
done

mkdir -p "$(dirname "${TRANSFER_LOG_PATH}")"
touch "${TRANSFER_LOG_PATH}"

_log() {
  echo "$1" | tee -a "${TRANSFER_LOG_PATH}"
}

if [[ -z "${REMOTE_BASE_DIR}" ]]; then
  _log "[stage11c][upload] ERROR: REMOTE_BASE_DIR is required."
  exit 2
fi
if [[ ! -d "${LOCAL_EXPORT_DIR}" ]]; then
  _log "[stage11c][upload] ERROR: LOCAL_EXPORT_DIR not found: ${LOCAL_EXPORT_DIR}"
  exit 2
fi

REMOTE_EXPORT_DIR="${REMOTE_BASE_DIR}/exports/reranker"
REMOTE_CHECKPOINT_TARGET="${REMOTE_BASE_DIR}/checkpoints"

_log "[stage11c][upload] remote_host=${REMOTE_HOST}"
_log "[stage11c][upload] remote_port=${REMOTE_PORT}"
_log "[stage11c][upload] remote_user=${REMOTE_USER}"
_log "[stage11c][upload] remote_base_dir=${REMOTE_BASE_DIR}"
_log "[stage11c][upload] local_export_dir=${LOCAL_EXPORT_DIR}"
_log "[stage11c][upload] local_checkpoint_dir=${LOCAL_CHECKPOINT_DIR}"
_log "[stage11c][upload] dry_run=${DRY_RUN}"
_log "[stage11c][upload] local_simulation=${LOCAL_SIMULATION}"

if [[ "${LOCAL_SIMULATION}" == "1" ]]; then
  _log "[stage11c][upload] mode=local_simulation"
  if [[ "${DRY_RUN}" == "1" ]]; then
    _log "[stage11c][upload] DRY_RUN mkdir -p \"${REMOTE_EXPORT_DIR}\" \"${REMOTE_CHECKPOINT_TARGET}\""
    _log "[stage11c][upload] DRY_RUN cp -r \"${LOCAL_EXPORT_DIR}/.\" \"${REMOTE_EXPORT_DIR}/\""
    exit 0
  fi
  mkdir -p "${REMOTE_EXPORT_DIR}" "${REMOTE_CHECKPOINT_TARGET}"
  cp -r "${LOCAL_EXPORT_DIR}/." "${REMOTE_EXPORT_DIR}/"
  _log "[stage11c][upload] copied to simulated remote dir: ${REMOTE_EXPORT_DIR}"
  exit 0
fi

if [[ -z "${REMOTE_HOST}" || -z "${REMOTE_USER}" ]]; then
  _log "[stage11c][upload] ERROR: REMOTE_HOST and REMOTE_USER are required when not in local_simulation mode."
  exit 2
fi

SSH_TARGET="${REMOTE_USER}@${REMOTE_HOST}"
SSH_MKDIR_CMD="mkdir -p \"${REMOTE_EXPORT_DIR}\" \"${REMOTE_CHECKPOINT_TARGET}\""
SCP_CMD=(scp -P "${REMOTE_PORT}" -r "${LOCAL_EXPORT_DIR}/." "${SSH_TARGET}:${REMOTE_EXPORT_DIR}/")

if [[ "${DRY_RUN}" == "1" ]]; then
  _log "[stage11c][upload] DRY_RUN ssh -p ${REMOTE_PORT} ${SSH_TARGET} ${SSH_MKDIR_CMD}"
  _log "[stage11c][upload] DRY_RUN ${SCP_CMD[*]}"
  exit 0
fi

ssh -p "${REMOTE_PORT}" "${SSH_TARGET}" "${SSH_MKDIR_CMD}" | tee -a "${TRANSFER_LOG_PATH}"
"${SCP_CMD[@]}" | tee -a "${TRANSFER_LOG_PATH}"
_log "[stage11c][upload] upload completed."
