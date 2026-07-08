"""Unified LLM harness with schema validation and run logging."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import time
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from src.db.models import LLMRun


class LLMHarnessError(RuntimeError):
    """Base harness error."""


class LLMHarnessSchemaError(LLMHarnessError):
    """Raised when structured output does not match the requested schema."""


@dataclass
class LLMHarnessResult:
    run_id: str
    status: str
    output: dict[str, Any]
    attempt_count: int
    fallback_used: bool
    schema_valid: bool
    latency_ms: int


class LLMHarness:
    """Run prompt calls through a logged, schema-aware execution boundary."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        backend: Any,
        fallback_backend: Any | None = None,
        max_retries: int = 1,
        cost_per_1k_tokens: float = 0.0,
    ) -> None:
        self.session_factory = session_factory
        self.backend = backend
        self.fallback_backend = fallback_backend
        self.max_retries = max(1, int(max_retries or 1))
        self.cost_per_1k_tokens = float(cost_per_1k_tokens or 0.0)

    def run_prompt(
        self,
        *,
        prompt_key: str,
        input: dict[str, Any],
        schema: dict[str, Any] | None = None,
        model_role: str | None = None,
        task_id: str | None = None,
        prompt: str | None = None,
        prompt_version_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LLMHarnessResult:
        run_id = f"llm_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{uuid4().hex[:8]}"
        started = time.perf_counter()
        attempt_count = 0
        fallback_used = False
        last_error: Exception | None = None
        attempt_errors: list[dict[str, Any]] = []
        output: dict[str, Any] | None = None
        backend_used = self.backend

        for backend, is_fallback in self._backend_sequence():
            backend_used = backend
            fallback_used = is_fallback
            attempts_for_backend = 1 if is_fallback else self.max_retries
            for _ in range(attempts_for_backend):
                attempt_count += 1
                try:
                    output = self._call_backend(backend, prompt=prompt or prompt_key, input=input, schema=schema)
                    _validate_schema(output, schema)
                    latency_ms = _elapsed_ms(started)
                    run_metadata = _merge_metadata(metadata, attempt_errors=attempt_errors)
                    self._record_run(
                        run_id=run_id,
                        task_id=task_id,
                        prompt_key=prompt_key,
                        prompt_version_id=prompt_version_id,
                        model_role=model_role,
                        backend=backend_used,
                        status="success",
                        attempt_count=attempt_count,
                        fallback_used=fallback_used,
                        schema_valid=True,
                        input_json=input,
                        output_json=output,
                        error_message=None,
                        latency_ms=latency_ms,
                        metadata=run_metadata,
                    )
                    return LLMHarnessResult(
                        run_id=run_id,
                        status="success",
                        output=output,
                        attempt_count=attempt_count,
                        fallback_used=fallback_used,
                        schema_valid=True,
                        latency_ms=latency_ms,
                    )
                except Exception as exc:  # noqa: BLE001 - harness must log all backend failures.
                    last_error = exc
                    attempt_errors.append(
                        {
                            "backend": _backend_name(backend),
                            "attempt": attempt_count,
                            "fallback": is_fallback,
                            "error": str(exc),
                        }
                    )

        latency_ms = _elapsed_ms(started)
        run_metadata = _merge_metadata(metadata, attempt_errors=attempt_errors)
        self._record_run(
            run_id=run_id,
            task_id=task_id,
            prompt_key=prompt_key,
            prompt_version_id=prompt_version_id,
            model_role=model_role,
            backend=backend_used,
            status="failed",
            attempt_count=attempt_count,
            fallback_used=fallback_used,
            schema_valid=False if schema else None,
            input_json=input,
            output_json=output,
            error_message=str(last_error) if last_error else "LLM harness failed",
            latency_ms=latency_ms,
            metadata=run_metadata,
        )
        if isinstance(last_error, LLMHarnessSchemaError):
            raise last_error
        raise LLMHarnessError(str(last_error) if last_error else "LLM harness failed")

    def _backend_sequence(self) -> list[tuple[Any, bool]]:
        sequence = [(self.backend, False)]
        if self.fallback_backend is not None:
            sequence.append((self.fallback_backend, True))
        return sequence

    def _call_backend(self, backend: Any, *, prompt: str, input: dict[str, Any], schema: dict[str, Any] | None) -> dict[str, Any]:
        if hasattr(backend, "generate_structured"):
            result = backend.generate_structured(prompt=prompt, schema=schema, **input)
        elif callable(backend):
            result = backend(prompt=prompt, schema=schema, **input)
        else:
            raise LLMHarnessError("Backend must be callable or implement generate_structured")
        if not isinstance(result, dict):
            raise LLMHarnessSchemaError("Structured LLM output must be a JSON object")
        return result

    def _record_run(
        self,
        *,
        run_id: str,
        task_id: str | None,
        prompt_key: str,
        prompt_version_id: int | None,
        model_role: str | None,
        backend: Any,
        status: str,
        attempt_count: int,
        fallback_used: bool,
        schema_valid: bool | None,
        input_json: dict[str, Any],
        output_json: dict[str, Any] | None,
        error_message: str | None,
        latency_ms: int,
        metadata: dict[str, Any] | None,
    ) -> None:
        prompt_tokens = _token_count(input_json)
        completion_tokens = _token_count(output_json or {})
        total_tokens = prompt_tokens + completion_tokens
        with self.session_factory() as session:
            session.add(
                LLMRun(
                    run_id=run_id,
                    task_id=task_id,
                    prompt_key=prompt_key,
                    prompt_version_id=prompt_version_id,
                    model_role=model_role,
                    model_name=getattr(backend, "name", None) or backend.__class__.__name__,
                    status=status,
                    attempt_count=attempt_count,
                    fallback_used=fallback_used,
                    schema_valid=schema_valid,
                    input_json=input_json,
                    output_json=output_json,
                    error_message=error_message,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    cost_usd=(total_tokens / 1000.0) * self.cost_per_1k_tokens,
                    latency_ms=latency_ms,
                    metadata_json=metadata or {},
                )
            )
            session.commit()


def serialize_llm_run(item: LLMRun) -> dict[str, Any]:
    return {
        "id": item.id,
        "run_id": item.run_id,
        "task_id": item.task_id,
        "prompt_key": item.prompt_key,
        "prompt_version_id": item.prompt_version_id,
        "model_role": item.model_role,
        "model_name": item.model_name,
        "status": item.status,
        "attempt_count": item.attempt_count,
        "fallback_used": item.fallback_used,
        "schema_valid": item.schema_valid,
        "input": item.input_json or {},
        "output": item.output_json or {},
        "error_message": item.error_message,
        "prompt_tokens": item.prompt_tokens,
        "completion_tokens": item.completion_tokens,
        "total_tokens": item.total_tokens,
        "cost_usd": item.cost_usd,
        "latency_ms": item.latency_ms,
        "metadata": item.metadata_json or {},
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


def _validate_schema(payload: dict[str, Any], schema: dict[str, Any] | None) -> None:
    if not schema:
        return
    if schema.get("type") and schema["type"] != "object":
        raise LLMHarnessSchemaError("Only object schemas are supported in the MVP harness")
    required = schema.get("required") or []
    for key in required:
        if key not in payload:
            raise LLMHarnessSchemaError(f"Missing required field: {key}")
    properties = schema.get("properties") or {}
    for key, rule in properties.items():
        if key not in payload:
            continue
        expected = rule.get("type") if isinstance(rule, dict) else None
        if expected and not _matches_type(payload[key], expected):
            raise LLMHarnessSchemaError(f"Field {key} expected {expected}")


def _matches_type(value: Any, expected: str | list[str]) -> bool:
    expected_values = expected if isinstance(expected, list) else [expected]
    checks = {
        "string": lambda item: isinstance(item, str),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "array": lambda item: isinstance(item, list),
        "object": lambda item: isinstance(item, dict),
        "null": lambda item: item is None,
    }
    return any(checks.get(kind, lambda _item: True)(value) for kind in expected_values)


def _token_count(payload: dict[str, Any]) -> int:
    text = str(payload)
    return max(1, len(text.split()))


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


def _backend_name(backend: Any) -> str:
    return str(getattr(backend, "name", None) or backend.__class__.__name__)


def _merge_metadata(metadata: dict[str, Any] | None, *, attempt_errors: list[dict[str, Any]]) -> dict[str, Any]:
    merged = dict(metadata or {})
    if attempt_errors:
        merged["attempt_errors"] = attempt_errors
    return merged
