"""Unified TaskBoard for visible multi-agent work state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Iterable, List


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    BLOCKED = "blocked"
    WAITING_REVIEW = "waiting_review"
    RESOLVED = "resolved"
    FAILED = "failed"


@dataclass(frozen=True)
class TaskBoardItem:
    task_id: str
    task_type: str
    owner_agent: str
    dependencies: List[str] = field(default_factory=list)
    related_gap_ids: List[str] = field(default_factory=list)
    status: TaskStatus = TaskStatus.QUEUED
    last_update: str = field(default_factory=lambda: now_iso())
    result_ref: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "owner_agent": self.owner_agent,
            "dependencies": list(self.dependencies),
            "related_gap_ids": list(self.related_gap_ids),
            "status": self.status.value,
            "last_update": self.last_update,
            "result_ref": self.result_ref,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "TaskBoardItem":
        return cls(
            task_id=str(payload.get("task_id", "")),
            task_type=str(payload.get("task_type", "")),
            owner_agent=str(payload.get("owner_agent", "")),
            dependencies=_str_list(payload.get("dependencies", [])),
            related_gap_ids=_str_list(payload.get("related_gap_ids", [])),
            status=parse_task_status(payload.get("status")),
            last_update=str(payload.get("last_update") or now_iso()),
            result_ref=str(payload.get("result_ref", "")),
        )

    def with_status(self, status: TaskStatus, result_ref: str | None = None) -> "TaskBoardItem":
        return TaskBoardItem(
            task_id=self.task_id,
            task_type=self.task_type,
            owner_agent=self.owner_agent,
            dependencies=list(self.dependencies),
            related_gap_ids=list(self.related_gap_ids),
            status=status,
            last_update=now_iso(),
            result_ref=self.result_ref if result_ref is None else result_ref,
        )


class TaskBoard:
    def __init__(self, tasks: Iterable[TaskBoardItem | Dict[str, Any]] | None = None):
        self._tasks: Dict[str, TaskBoardItem] = {}
        for item in tasks or []:
            task = item if isinstance(item, TaskBoardItem) else TaskBoardItem.from_dict(dict(item))
            if task.task_id:
                self._tasks[task.task_id] = task

    def upsert(self, item: TaskBoardItem | Dict[str, Any]) -> None:
        task = item if isinstance(item, TaskBoardItem) else TaskBoardItem.from_dict(dict(item))
        self._tasks[task.task_id] = task

    def update_status(self, task_id: str, status: TaskStatus, result_ref: str | None = None) -> None:
        existing = self._tasks.get(task_id)
        if existing is None:
            self._tasks[task_id] = TaskBoardItem(task_id=task_id, task_type="unknown", owner_agent="unknown", status=status, result_ref=result_ref or "")
            return
        self._tasks[task_id] = existing.with_status(status=status, result_ref=result_ref)

    def add_gap_task(self, gap_id: str, gap_type: str, owner_agent: str, dependencies: List[str] | None = None) -> TaskBoardItem:
        task_id = f"gap_task_{gap_id}_{owner_agent}".replace(" ", "_")
        item = TaskBoardItem(
            task_id=task_id,
            task_type=f"gap_rework:{gap_type}",
            owner_agent=owner_agent,
            dependencies=list(dependencies or []),
            related_gap_ids=[gap_id],
            status=TaskStatus.QUEUED,
        )
        self.upsert(item)
        return item

    def open_tasks(self) -> List[Dict[str, Any]]:
        open_status = {TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.BLOCKED, TaskStatus.WAITING_REVIEW}
        return [task.to_dict() for task in self._tasks.values() if task.status in open_status]

    def blocked_count(self) -> int:
        return sum(1 for task in self._tasks.values() if task.status == TaskStatus.BLOCKED)

    def resolution_rate(self) -> float:
        tasks = list(self._tasks.values())
        if not tasks:
            return 0.0
        resolved = sum(1 for task in tasks if task.status == TaskStatus.RESOLVED)
        return round(resolved / float(len(tasks)), 4)

    def to_dict(self) -> Dict[str, Any]:
        tasks = [task.to_dict() for task in sorted(self._tasks.values(), key=lambda item: item.task_id)]
        return {
            "tasks": tasks,
            "summary": {
                "task_count": len(tasks),
                "blocked_count": self.blocked_count(),
                "resolution_rate": self.resolution_rate(),
            },
        }

    @classmethod
    def from_plan_tasks(cls, tasks: Iterable[Any], owner_resolver: Any) -> "TaskBoard":
        board = cls()
        for task in tasks:
            task_id = str(getattr(task, "task_id", ""))
            task_type = str(getattr(task, "task_type", ""))
            dependencies = list(getattr(task, "dependencies", []))
            try:
                owner = str(owner_resolver(task_type))
            except Exception:
                owner = "unknown"
            board.upsert(TaskBoardItem(task_id=task_id, task_type=task_type, owner_agent=owner, dependencies=dependencies))
        return board


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_task_status(value: Any) -> TaskStatus:
    text = str(value or TaskStatus.QUEUED.value).strip().lower()
    for status in TaskStatus:
        if status.value == text:
            return status
    return TaskStatus.QUEUED


def _str_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]
