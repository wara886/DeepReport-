"""LangGraph adapter for the canonical financial-report runtime state.

The graph owns orchestration, checkpoints, failure resume, and human review.
Business truth remains the ``ReportRunState`` projection defined in
``report_run_state.py``; nodes may only return typed partial updates to it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import operator
from pathlib import Path
import sqlite3
import time
from typing import Annotated, Any, Protocol, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from typing_extensions import NotRequired

from src.runtime.report_run_state import DeliveryReadiness, ReportLifecycleStatus, ReportRunState


class ReportGraphState(ReportRunState, total=False):
    """Canonical report state plus graph-only execution metadata."""

    runtime_events: Annotated[list[dict[str, Any]], operator.add]
    last_node: str
    review_decision: NotRequired[dict[str, Any]]
    request_id: NotRequired[str]
    run_id: NotRequired[str]


class EvidenceNodePatch(TypedDict, total=False):
    lifecycle_status: ReportLifecycleStatus
    evidence_state: dict[str, Any]
    delivery_readiness: DeliveryReadiness
    export_readiness: dict[str, Any]


class GenerationNodePatch(TypedDict, total=False):
    lifecycle_status: ReportLifecycleStatus
    artifact_state: dict[str, Any]
    claim_state: dict[str, Any]
    delivery_readiness: DeliveryReadiness
    export_readiness: dict[str, Any]


class QualityNodePatch(TypedDict, total=False):
    lifecycle_status: ReportLifecycleStatus
    quality_state: dict[str, Any]
    delivery_readiness: DeliveryReadiness
    export_readiness: dict[str, Any]


class ReviewNodePatch(TypedDict, total=False):
    claim_state: dict[str, Any]
    delivery_readiness: DeliveryReadiness
    export_readiness: dict[str, Any]
    review_decision: dict[str, Any]


class ReportGraphHandlers(Protocol):
    def evidence(self, state: ReportGraphState) -> dict[str, Any]: ...

    def official_evidence_backfill(self, state: ReportGraphState) -> dict[str, Any]: ...

    def build_canonical_metrics(self, state: ReportGraphState) -> dict[str, Any]: ...

    def build_section_evidence_packs(self, state: ReportGraphState) -> dict[str, Any]: ...

    def generation(self, state: ReportGraphState) -> dict[str, Any]: ...

    def verify_sections(self, state: ReportGraphState) -> dict[str, Any]: ...

    def repair_failed_sections(self, state: ReportGraphState) -> dict[str, Any]: ...

    def quality(self, state: ReportGraphState) -> dict[str, Any]: ...

    def finalize(self, state: ReportGraphState) -> dict[str, Any]: ...

    def review(self, state: ReportGraphState, decision: Any) -> dict[str, Any]: ...


@dataclass
class CallbackReportGraphHandlers:
    evidence_callback: Callable[[ReportGraphState], dict[str, Any]]
    generation_callback: Callable[[ReportGraphState], dict[str, Any]]
    quality_callback: Callable[[ReportGraphState], dict[str, Any]]
    finalize_callback: Callable[[ReportGraphState], dict[str, Any]]
    review_callback: Callable[[ReportGraphState, Any], dict[str, Any]] | None = None
    official_evidence_backfill_callback: Callable[[ReportGraphState], dict[str, Any]] | None = None
    build_canonical_metrics_callback: Callable[[ReportGraphState], dict[str, Any]] | None = None
    build_section_evidence_packs_callback: Callable[[ReportGraphState], dict[str, Any]] | None = None
    verify_sections_callback: Callable[[ReportGraphState], dict[str, Any]] | None = None
    repair_failed_sections_callback: Callable[[ReportGraphState], dict[str, Any]] | None = None

    def evidence(self, state: ReportGraphState) -> dict[str, Any]:
        return self.evidence_callback(state)

    def official_evidence_backfill(self, state: ReportGraphState) -> dict[str, Any]:
        if self.official_evidence_backfill_callback is None:
            return {}
        return self.official_evidence_backfill_callback(state)

    def build_canonical_metrics(self, state: ReportGraphState) -> dict[str, Any]:
        if self.build_canonical_metrics_callback is None:
            return {}
        return self.build_canonical_metrics_callback(state)

    def build_section_evidence_packs(self, state: ReportGraphState) -> dict[str, Any]:
        if self.build_section_evidence_packs_callback is None:
            return {}
        return self.build_section_evidence_packs_callback(state)

    def generation(self, state: ReportGraphState) -> dict[str, Any]:
        return self.generation_callback(state)

    def verify_sections(self, state: ReportGraphState) -> dict[str, Any]:
        if self.verify_sections_callback is None:
            return {}
        return self.verify_sections_callback(state)

    def repair_failed_sections(self, state: ReportGraphState) -> dict[str, Any]:
        if self.repair_failed_sections_callback is None:
            return {}
        return self.repair_failed_sections_callback(state)

    def quality(self, state: ReportGraphState) -> dict[str, Any]:
        return self.quality_callback(state)

    def finalize(self, state: ReportGraphState) -> dict[str, Any]:
        return self.finalize_callback(state)

    def review(self, state: ReportGraphState, decision: Any) -> dict[str, Any]:
        if self.review_callback is None:
            return {}
        return self.review_callback(state, decision)


class LangGraphReportRuntime:
    """Execute the report lifecycle with checkpointed LangGraph nodes."""

    def __init__(
        self,
        handlers: ReportGraphHandlers,
        *,
        checkpointer: Any | None = None,
        checkpoint_path: str | Path | None = None,
    ) -> None:
        if checkpointer is not None and checkpoint_path is not None:
            raise ValueError("Use either checkpointer or checkpoint_path, not both")
        self.handlers = handlers
        self._connection: sqlite3.Connection | None = None
        if checkpoint_path is not None:
            path = Path(checkpoint_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(path, check_same_thread=False)
            checkpointer = SqliteSaver(self._connection)
            checkpointer.setup()
        self.checkpointer = checkpointer or MemorySaver()
        self.graph = self._build_graph().compile(
            checkpointer=self.checkpointer,
            name="deepreport_financial_report_runtime",
        )

    def invoke(self, state: ReportRunState | ReportGraphState, *, thread_id: str) -> dict[str, Any]:
        payload = dict(state)
        payload.setdefault("runtime_events", [])
        result = self.graph.invoke(payload, config=self._config(thread_id))
        return self._decorate_result(result, thread_id=thread_id)

    def resume(self, *, thread_id: str, decision: Any) -> dict[str, Any]:
        result = self.graph.invoke(Command(resume=decision), config=self._config(thread_id))
        return self._decorate_result(result, thread_id=thread_id)

    def retry_from_checkpoint(self, *, thread_id: str) -> dict[str, Any]:
        """Retry the pending node after a failure from its last checkpoint."""

        result = self.graph.invoke(None, config=self._config(thread_id))
        return self._decorate_result(result, thread_id=thread_id)

    def snapshot(self, *, thread_id: str) -> dict[str, Any]:
        snapshot = self.graph.get_state(self._config(thread_id))
        interrupts = []
        for task in snapshot.tasks or ():
            interrupts.extend(
                {
                    "id": getattr(item, "id", None),
                    "value": getattr(item, "value", None),
                }
                for item in (getattr(task, "interrupts", None) or ())
            )
        return {
            "values": dict(snapshot.values or {}),
            "next": list(snapshot.next or ()),
            "interrupts": interrupts,
            "created_at": snapshot.created_at,
            "metadata": dict(snapshot.metadata or {}),
        }

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _decorate_result(self, result: dict[str, Any], *, thread_id: str) -> dict[str, Any]:
        payload = dict(result)
        interrupts = self.snapshot(thread_id=thread_id)["interrupts"]
        if interrupts:
            payload["interrupts"] = interrupts
        return payload

    def _build_graph(self) -> StateGraph:
        builder = StateGraph(ReportGraphState)
        builder.add_node("evidence", self._evidence_node)
        builder.add_node("official_evidence_backfill", self._official_evidence_backfill_node)
        builder.add_node("build_canonical_metrics", self._build_canonical_metrics_node)
        builder.add_node("build_section_evidence_packs", self._build_section_evidence_packs_node)
        builder.add_node("generation", self._generation_node)
        builder.add_node("verify_sections", self._verify_sections_node)
        builder.add_node("repair_failed_sections", self._repair_failed_sections_node)
        builder.add_node("quality", self._quality_node)
        builder.add_node("finalize", self._finalize_node)
        builder.add_node("human_review", self._human_review_node)
        builder.add_edge(START, "evidence")
        builder.add_conditional_edges(
            "evidence",
            self._route_after_evidence,
            {"official_evidence_backfill": "official_evidence_backfill", "end": END},
        )
        builder.add_edge("official_evidence_backfill", "build_canonical_metrics")
        builder.add_edge("build_canonical_metrics", "build_section_evidence_packs")
        builder.add_edge("build_section_evidence_packs", "generation")
        builder.add_edge("generation", "verify_sections")
        builder.add_edge("verify_sections", "repair_failed_sections")
        builder.add_edge("repair_failed_sections", "quality")
        builder.add_edge("quality", "finalize")
        builder.add_conditional_edges(
            "finalize",
            self._route_after_finalize,
            {"human_review": "human_review", "end": END},
        )
        builder.add_edge("human_review", END)
        return builder

    def _evidence_node(self, state: ReportGraphState) -> dict[str, Any]:
        return self._execute_node("evidence", state, self.handlers.evidence)

    def _official_evidence_backfill_node(self, state: ReportGraphState) -> dict[str, Any]:
        return self._execute_node("official_evidence_backfill", state, self.handlers.official_evidence_backfill)

    def _build_canonical_metrics_node(self, state: ReportGraphState) -> dict[str, Any]:
        return self._execute_node("build_canonical_metrics", state, self.handlers.build_canonical_metrics)

    def _build_section_evidence_packs_node(self, state: ReportGraphState) -> dict[str, Any]:
        return self._execute_node("build_section_evidence_packs", state, self.handlers.build_section_evidence_packs)

    def _generation_node(self, state: ReportGraphState) -> dict[str, Any]:
        return self._execute_node("generation", state, self.handlers.generation)

    def _verify_sections_node(self, state: ReportGraphState) -> dict[str, Any]:
        return self._execute_node("verify_sections", state, self.handlers.verify_sections)

    def _repair_failed_sections_node(self, state: ReportGraphState) -> dict[str, Any]:
        return self._execute_node("repair_failed_sections", state, self.handlers.repair_failed_sections)

    def _quality_node(self, state: ReportGraphState) -> dict[str, Any]:
        return self._execute_node("quality", state, self.handlers.quality)

    def _finalize_node(self, state: ReportGraphState) -> dict[str, Any]:
        return self._execute_node("finalize", state, self.handlers.finalize)

    def _human_review_node(self, state: ReportGraphState) -> dict[str, Any]:
        decision = interrupt(
            {
                "type": "claim_review_required",
                "task_id": state.get("task_id"),
                "claim_state": state.get("claim_state", {}),
                "blocking_reasons": state.get("delivery_readiness", {}).get("blocking_reasons", []),
                "required_actions": state.get("delivery_readiness", {}).get("required_actions", []),
            }
        )
        started = time.perf_counter()
        patch = self.handlers.review(state, decision)
        patch["review_decision"] = _decision_payload(decision)
        return self._node_patch("human_review", patch, state=state, duration_ms=(time.perf_counter() - started) * 1000)

    def _execute_node(
        self,
        node: str,
        state: ReportGraphState,
        callback: Callable[[ReportGraphState], dict[str, Any]],
    ) -> dict[str, Any]:
        started = time.perf_counter()
        patch = callback(state)
        return self._node_patch(node, patch, state=state, duration_ms=(time.perf_counter() - started) * 1000)

    @staticmethod
    def _route_after_evidence(state: ReportGraphState) -> str:
        evidence = state.get("evidence_state", {})
        if state.get("lifecycle_status") == "evidence_blocked" or evidence.get("blocked") is True:
            return "end"
        return "official_evidence_backfill"

    @staticmethod
    def _route_after_finalize(state: ReportGraphState) -> str:
        blockers = set(state.get("delivery_readiness", {}).get("blocking_reasons", []))
        return "human_review" if "pending_claim_review" in blockers else "end"

    @staticmethod
    def _node_patch(
        node: str,
        raw_patch: dict[str, Any] | None,
        *,
        state: ReportGraphState | None = None,
        duration_ms: float = 0.0,
    ) -> dict[str, Any]:
        patch = dict(raw_patch or {})
        unknown = set(patch).difference(_PATCHABLE_STATE_KEYS)
        if unknown:
            raise ValueError(f"Node {node} returned unsupported state keys: {sorted(unknown)}")
        patch["last_node"] = node
        trace = state or {}
        patch["runtime_events"] = [
            {
                "node": node,
                "status": "completed",
                "task_id": trace.get("task_id"),
                "run_id": trace.get("run_id") or trace.get("task_id"),
                "request_id": trace.get("request_id") or trace.get("task_id"),
                "duration_ms": round(float(duration_ms), 3),
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
        ]
        return patch

    @staticmethod
    def _config(thread_id: str) -> dict[str, Any]:
        if not str(thread_id or "").strip():
            raise ValueError("thread_id is required for checkpointed report runs")
        return {"configurable": {"thread_id": str(thread_id)}}


_PATCHABLE_STATE_KEYS = set(ReportRunState.__annotations__) | {
    "review_decision",
}


def project_run_state_patch(run_state: ReportRunState) -> dict[str, Any]:
    """Return only canonical business keys for a graph node update."""

    return {key: value for key, value in run_state.items() if key in _PATCHABLE_STATE_KEYS}


def _decision_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {"approved": bool(value), "value": value}
