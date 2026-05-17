"""Base abstractions for LLM-driven financial agents."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Callable, Dict, List

from src.models import ModelAdapter


class AgentStatus(str, Enum):
    """Runtime task status used by agent execution."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AgentTask:
    """A unit of work routed to one financial research agent."""

    task_id: str
    task_type: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)
    priority: int = 3
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentTask":
        return cls(
            task_id=str(data["task_id"]),
            task_type=str(data["task_type"]),
            description=str(data.get("description", "")),
            parameters=dict(data.get("parameters", {})),
            dependencies=[str(item) for item in data.get("dependencies", [])],
            priority=int(data.get("priority", 3)),
            metadata=dict(data.get("metadata", {})),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "description": self.description,
            "parameters": dict(self.parameters),
            "dependencies": list(self.dependencies),
            "priority": self.priority,
            "metadata": dict(self.metadata),
        }


@dataclass
class TaskResult:
    """Normalized result produced by an agent."""

    task_id: str
    agent_name: str
    status: AgentStatus
    output: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskResult":
        return cls(
            task_id=str(data["task_id"]),
            agent_name=str(data["agent_name"]),
            status=AgentStatus(str(data["status"])),
            output=dict(data.get("output", {})),
            error=str(data.get("error", "")),
            metadata=dict(data.get("metadata", {})),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "agent_name": self.agent_name,
            "status": self.status.value,
            "output": dict(self.output),
            "error": self.error,
            "metadata": dict(self.metadata),
        }


ToolFn = Callable[..., Any]


class BaseAgent(ABC):
    """Base class shared by all real LLM-driven agents."""

    def __init__(
        self,
        name: str,
        model: ModelAdapter | None = None,
        tools: Dict[str, ToolFn] | None = None,
    ):
        self.name = name
        self.model = model
        self.tools = tools or {}
        self.memory: List[Dict[str, Any]] = []
        self.tool_trace: List[Dict[str, Any]] = []

    @abstractmethod
    def get_capabilities(self) -> List[str]:
        """Return a human-readable capability list for routing/planning."""

    @abstractmethod
    def execute_task(self, task: AgentTask) -> TaskResult:
        """Execute one task and return a normalized result."""

    def remember(self, item: Dict[str, Any]) -> None:
        self.memory.append(dict(item))

    def get_tool_names(self) -> List[str]:
        return sorted(self.tools.keys())

    def call_tool(self, name: str, **kwargs: Any) -> Any:
        if name not in self.tools:
            raise KeyError(f"tool not registered for {self.name}: {name}")
        started = time.perf_counter()
        try:
            result = self.tools[name](**kwargs)
        except Exception as exc:
            self.tool_trace.append(
                {
                    "caller_agent": self.name,
                    "tool_name": name,
                    "input_summary": _summarize_value(kwargs),
                    "output_summary": {},
                    "success": False,
                    "failure_reason": str(exc),
                    "duration_sec": round(time.perf_counter() - started, 3),
                    "evidence_ids": [],
                    "artifact_paths": [],
                }
            )
            raise
        self.tool_trace.append(
            {
                "caller_agent": self.name,
                "tool_name": name,
                "input_summary": _summarize_value(kwargs),
                "output_summary": _summarize_value(result),
                "success": True,
                "failure_reason": "",
                "duration_sec": round(time.perf_counter() - started, 3),
                "evidence_ids": _extract_evidence_ids(result),
                "artifact_paths": _extract_artifact_paths(result),
            }
        )
        return result

    def success(
        self,
        task: AgentTask,
        output: Dict[str, Any],
        metadata: Dict[str, Any] | None = None,
    ) -> TaskResult:
        result = TaskResult(
            task_id=task.task_id,
            agent_name=self.name,
            status=AgentStatus.COMPLETED,
            output=output,
            metadata=metadata or {},
        )
        self.remember({"task": task.to_dict(), "result": result.to_dict()})
        return result

    def failure(
        self,
        task: AgentTask,
        error: str,
        metadata: Dict[str, Any] | None = None,
    ) -> TaskResult:
        result = TaskResult(
            task_id=task.task_id,
            agent_name=self.name,
            status=AgentStatus.FAILED,
            error=error,
            metadata=metadata or {},
        )
        self.remember({"task": task.to_dict(), "result": result.to_dict()})
        return result


def _summarize_value(value: Any, limit: int = 180) -> Any:
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, str):
        return value if len(value) <= limit else value[: limit - 3] + "..."
    if isinstance(value, list):
        return {"type": "list", "count": len(value), "sample": [_summarize_value(item, 80) for item in value[:3]]}
    if isinstance(value, dict):
        summary: Dict[str, Any] = {"type": "dict", "keys": sorted(str(key) for key in list(value.keys())[:12])}
        for key in ["rows", "claims", "charts", "tables", "records", "evidence_records"]:
            if isinstance(value.get(key), list):
                summary[f"{key}_count"] = len(value[key])
        for key in ["valuation_available", "peer_count", "symbol", "period"]:
            if key in value:
                summary[key] = _summarize_value(value[key], 80)
        return summary
    return _summarize_value(str(value), limit)


def _extract_evidence_ids(value: Any) -> List[str]:
    found: List[str] = []

    def walk(item: Any) -> None:
        if len(found) >= 20:
            return
        if isinstance(item, dict):
            for key in ["evidence_id", "sample_id"]:
                raw = item.get(key)
                if raw:
                    found.append(str(raw))
            for raw in item.get("evidence_ids", []) if isinstance(item.get("evidence_ids"), list) else []:
                if raw:
                    found.append(str(raw))
            for nested in item.values():
                walk(nested)
        elif isinstance(item, list):
            for nested in item[:20]:
                walk(nested)

    walk(value)
    return sorted(set(found))[:20]


def _extract_artifact_paths(value: Any) -> List[str]:
    paths: List[str] = []

    def walk(item: Any) -> None:
        if len(paths) >= 20:
            return
        if isinstance(item, dict):
            for key, raw in item.items():
                if isinstance(raw, str) and ("path" in str(key).lower() or raw.endswith((".json", ".md", ".html", ".png"))):
                    paths.append(raw)
                else:
                    walk(raw)
        elif isinstance(item, list):
            for nested in item[:20]:
                walk(nested)

    walk(value)
    return sorted(set(paths))[:20]
