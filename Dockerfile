FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=7860 \
    APP_MODE=user

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY main.py ./
COPY configs ./configs
COPY scripts ./scripts
COPY src ./src

RUN pip install --no-cache-dir ".[pdf]"

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data/outputs_user /app/data/reports_user /app/data/evidence_archive /app/memory \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:7860/health || exit 1

CMD ["sh", "-c", "python main.py --mode ${APP_MODE:-user} --port ${PORT:-7860}"]
