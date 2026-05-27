#!/usr/bin/env sh
set -eu

if [ ! -f .env ]; then
  cp .env.example .env
  printf '%s\n' 'Created .env from .env.example; add credentials for remote report generation.'
fi

docker compose up --build -d
printf '%s\n' 'FinSight is starting at http://localhost:7860'
