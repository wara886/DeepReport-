"""Deployable ASGI entrypoint for FinSight."""

from __future__ import annotations

import os

import uvicorn

from src.app.api_fastapi import app


if __name__ == "__main__":
    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "7860")))
