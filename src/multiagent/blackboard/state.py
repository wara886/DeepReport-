"""Shared Blackboard wrapper for replayable multi-agent state."""

from __future__ import annotations

from typing import Any, Dict, List

from src.multiagent.gaps.schema import GapItem
from src.multiagent.messages.schema import AgentMessage
from src.multiagent.taskboard.board import TaskBoard, TaskBoardItem


class Blackboard:
    def __init__(self, state: Dict[str, Any] | None = None, task_board: TaskBoard | None = None):
        self.state = state if state is not None else {}
        board_payload = self.state.get("task_board", {})
        if task_board is not None:
            self.task_board = task_board
        elif isinstance(board_payload, dict) and isinstance(board_payload.get("tasks"), list):
            self.task_board = TaskBoard(board_payload.get("tasks", []))
        else:
            self.task_board = TaskBoard()
        self.state["task_board"] = self.task_board.to_dict()
        self.state.setdefault("agent_messages", [])
        self.state.setdefault("gaps", [])

    def read_state(self, key: str = "") -> Any:
        if not key:
            return self.state
        return self.state.get(key)

    def write_state(self, key: str, value: Any) -> None:
        self.state[key] = value

    def append_message(self, message: AgentMessage | Dict[str, Any]) -> None:
        payload = message.to_dict() if isinstance(message, AgentMessage) else dict(message)
        self.state.setdefault("agent_messages", []).append(payload)

    def append_gap(self, gap: GapItem | Dict[str, Any]) -> None:
        payload = gap.to_dict() if isinstance(gap, GapItem) else dict(gap)
        self.state.setdefault("gaps", []).append(payload)

    def upsert_task(self, task: TaskBoardItem | Dict[str, Any]) -> None:
        self.task_board.upsert(task)
        self.sync_task_board()

    def update_task_board(self, task_board: TaskBoard) -> None:
        self.task_board = task_board
        self.sync_task_board()

    def sync_task_board(self) -> None:
        self.state["task_board"] = self.task_board.to_dict()

    def get_open_tasks(self) -> List[Dict[str, Any]]:
        return self.task_board.open_tasks()
