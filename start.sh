#!/usr/bin/env sh
set -eu

if [ ! -f .env ]; then
  cp .env.example .env
  printf '%s\n' 'Created .env from .env.example; add credentials for remote report generation.'
fi

export HF_HOME="${HF_HOME:-$(pwd)/models/huggingface}"
export SENTENCE_TRANSFORMERS_HOME="${SENTENCE_TRANSFORMERS_HOME:-$(pwd)/models/sentence_transformers}"
export TRANSFORMERS_CACHE="${TRANSFORMERS_CACHE:-$(pwd)/models/huggingface/transformers}"
export HF_HUB_DISABLE_SYMLINKS_WARNING="${HF_HUB_DISABLE_SYMLINKS_WARNING:-1}"

docker compose up --build -d
printf '%s\n' 'FinSight is starting at http://localhost:7860'
