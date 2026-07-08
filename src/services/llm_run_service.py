"""LLM run query service for Harness observability."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import LLMRun
from src.llm.harness import serialize_llm_run


class LLMRunNotFound(LookupError):
    """Raised when an LLM run does not exist."""


class LLMRunService:
    def __init__(self, *, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    def list_runs(
        self,
        *,
        task_id: str | None = None,
        prompt_key: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit or 100), 300))
        with self.session_factory() as session:
            stmt = select(LLMRun).order_by(LLMRun.created_at.desc(), LLMRun.id.desc()).limit(limit)
            count_stmt = select(LLMRun)
            if task_id:
                stmt = stmt.where(LLMRun.task_id == task_id)
                count_stmt = count_stmt.where(LLMRun.task_id == task_id)
            if prompt_key:
                stmt = stmt.where(LLMRun.prompt_key == prompt_key)
                count_stmt = count_stmt.where(LLMRun.prompt_key == prompt_key)
            if status:
                stmt = stmt.where(LLMRun.status == status)
                count_stmt = count_stmt.where(LLMRun.status == status)
            items = [serialize_llm_run(item) for item in session.scalars(stmt).all()]
            total = len(session.scalars(count_stmt).all())
        return {"items": items, "total": total}

    def get_run(self, run_ref: int | str) -> dict[str, Any]:
        with self.session_factory() as session:
            text = str(run_ref).strip()
            condition = LLMRun.id == int(text) if text.isdigit() else LLMRun.run_id == text
            item = session.scalar(select(LLMRun).where(condition))
            if item is None:
                raise LLMRunNotFound(text)
            return serialize_llm_run(item)
