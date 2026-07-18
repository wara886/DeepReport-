"""Small ReAct/tool-calling loop shared by financial agents."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
import time
from typing import Any, Callable, Dict, List

from src.models import ModelAdapter, ModelResponse


ToolHandler = Callable[..., Any]


def run_react_tool_loop(
    model: ModelAdapter,
    system_prompt: str,
    user_prompt: str,
    tool_schemas: List[Dict[str, Any]],
    handlers: Dict[str, ToolHandler],
    max_steps: int = 3,
    max_observation_chars: int = 3000,
    max_tool_calls: int = 8,
    tool_timeout_seconds: float = 45.0,
    tool_max_attempts: int = 2,
    bound_arguments: Dict[str, Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Let the model choose tools, execute them, and feed observations back."""

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    trace: List[Dict[str, Any]] = []
    observations: List[Dict[str, Any]] = []
    schema_by_name = _schemas_by_name(tool_schemas)
    bound_arguments = bound_arguments or {}
    tool_call_count = 0
    had_tool_error = False

    for step_index in range(1, max_steps + 1):
        response = model.chat(messages=messages, tools=tool_schemas, tool_choice="auto")
        if not response.success:
            return {
                "success": False,
                "final_content": "",
                "trace": trace,
                "observations": observations,
                "error": response.error,
            }

        tool_calls = response.tool_calls or []
        if not tool_calls:
            return {
                "success": True,
                "status": "degraded" if had_tool_error else "completed",
                "final_content": response.content,
                "trace": trace,
                "observations": observations,
                "error": "",
            }

        messages.append(_assistant_tool_call_message(response))
        for call in tool_calls:
            call_id = str(call.get("id") or f"call_{step_index}_{len(trace) + 1}")
            tool_call_count += 1
            if tool_call_count > max_tool_calls:
                return {
                    "success": False,
                    "status": "failed",
                    "final_content": "",
                    "trace": trace,
                    "observations": observations,
                    "error": "tool_call_budget_exceeded",
                }

            try:
                tool_name, model_arguments = _parse_tool_call(call)
                arguments = dict(model_arguments)
                arguments.update(bound_arguments.get(tool_name, {}))
                validation_errors = _validate_arguments(arguments, schema_by_name.get(tool_name, {}))
                if validation_errors:
                    observation = {
                        "error": "; ".join(validation_errors),
                        "error_type": "invalid_arguments",
                    }
                    attempts = 0
                    duration_ms = 0.0
                elif tool_name not in handlers:
                    observation = {"error": f"unknown tool: {tool_name}", "error_type": "unknown_tool"}
                    attempts = 0
                    duration_ms = 0.0
                else:
                    observation, attempts, duration_ms = _invoke_tool(
                        handlers[tool_name],
                        arguments=arguments,
                        timeout_seconds=tool_timeout_seconds,
                        max_attempts=tool_max_attempts,
                    )
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                tool_name = _tool_name(call)
                model_arguments = {}
                arguments = dict(bound_arguments.get(tool_name, {}))
                validation_errors = _validate_arguments(arguments, schema_by_name.get(tool_name, {}))
                if arguments and not validation_errors and tool_name in handlers:
                    observation, attempts, duration_ms = _invoke_tool(
                        handlers[tool_name],
                        arguments=arguments,
                        timeout_seconds=tool_timeout_seconds,
                        max_attempts=tool_max_attempts,
                    )
                else:
                    detail = "; ".join(validation_errors) if validation_errors else str(exc)
                    observation = {"error": detail, "error_type": "invalid_arguments"}
                    attempts = 0
                    duration_ms = 0.0

            if isinstance(observation, dict) and observation.get("error"):
                had_tool_error = True

            observation_text = _json_preview(observation, max_chars=max_observation_chars)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": tool_name,
                    "content": observation_text,
                }
            )
            observations.append(
                {
                    "tool_name": tool_name,
                    "arguments": _summarize_arguments(arguments),
                    "result": observation,
                    "attempts": attempts,
                    "duration_ms": round(duration_ms, 3),
                }
            )
            trace.append(
                {
                    "step": step_index,
                    "tool_name": tool_name,
                    "arguments": _summarize_arguments(arguments),
                    "attempts": attempts,
                    "duration_ms": round(duration_ms, 3),
                    "output_summary": _summarize_result(observation),
                    "evidence_ids": _extract_evidence_ids(observation),
                    "error_type": observation.get("error_type", "") if isinstance(observation, dict) else "",
                    "observation_preview": observation_text[:500],
                    "error": observation.get("error", "") if isinstance(observation, dict) else "",
                }
            )

    return {
        "success": False,
        "status": "failed",
        "final_content": "",
        "trace": trace,
        "observations": observations,
        "error": "max_steps_reached",
    }


def _assistant_tool_call_message(response: ModelResponse) -> Dict[str, Any]:
    message: Dict[str, Any] = {
        "role": "assistant",
        "content": response.content or "",
        "tool_calls": response.tool_calls or [],
    }
    if response.reasoning_content:
        message["reasoning_content"] = response.reasoning_content
    return message


def _parse_tool_call(call: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    function = call.get("function", {}) if isinstance(call, dict) else {}
    tool_name = str(function.get("name", "")).strip()
    raw_arguments = function.get("arguments", "{}")
    if isinstance(raw_arguments, dict):
        arguments = raw_arguments
    else:
        arguments = json.loads(str(raw_arguments or "{}"))
    if not isinstance(arguments, dict):
        arguments = {}
    return tool_name, arguments


def _tool_name(call: Dict[str, Any]) -> str:
    function = call.get("function", {}) if isinstance(call, dict) else {}
    return str(function.get("name", "")).strip()


def _schemas_by_name(tool_schemas: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    output: Dict[str, Dict[str, Any]] = {}
    for schema in tool_schemas:
        function = schema.get("function", {}) if isinstance(schema, dict) else {}
        name = str(function.get("name") or "").strip()
        if name:
            output[name] = function.get("parameters", {}) if isinstance(function.get("parameters"), dict) else {}
    return output


def _validate_arguments(arguments: Dict[str, Any], schema: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    required = schema.get("required", []) if isinstance(schema.get("required"), list) else []
    for name in required:
        if name not in arguments:
            errors.append(f"missing required argument: {name}")
    properties = schema.get("properties", {}) if isinstance(schema.get("properties"), dict) else {}
    for name, value in arguments.items():
        definition = properties.get(name)
        if not isinstance(definition, dict):
            continue
        expected = str(definition.get("type") or "")
        if expected and not _matches_json_type(value, expected):
            errors.append(f"argument {name} must be {expected}")
            continue
        enum = definition.get("enum")
        if isinstance(enum, list) and value not in enum:
            errors.append(f"argument {name} must be one of {enum}")
    return errors


def _matches_json_type(value: Any, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "null":
        return value is None
    return True


def _invoke_tool(
    handler: ToolHandler,
    *,
    arguments: Dict[str, Any],
    timeout_seconds: float,
    max_attempts: int,
) -> tuple[Any, int, float]:
    attempts = max(1, int(max_attempts or 1))
    started = time.perf_counter()
    last_error: Dict[str, Any] = {"error": "tool execution failed", "error_type": "tool_error"}
    for attempt in range(1, attempts + 1):
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="react-tool")
        future = executor.submit(handler, **arguments)
        try:
            result = future.result(timeout=max(float(timeout_seconds), 0.01))
            executor.shutdown(wait=False, cancel_futures=True)
            return result, attempt, (time.perf_counter() - started) * 1000
        except FutureTimeoutError:
            future.cancel()
            last_error = {
                "error": f"tool timed out after {timeout_seconds}s",
                "error_type": "tool_timeout",
            }
        except Exception as exc:
            last_error = {"error": str(exc), "error_type": "tool_error"}
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
    return last_error, attempts, (time.perf_counter() - started) * 1000


def _summarize_arguments(arguments: Dict[str, Any]) -> Dict[str, Any]:
    output: Dict[str, Any] = {}
    for name, value in arguments.items():
        if isinstance(value, list):
            output[name] = {"type": "array", "count": len(value)}
        elif isinstance(value, dict):
            output[name] = {"type": "object", "keys": sorted(str(key) for key in value)[:20]}
        elif isinstance(value, str) and len(value) > 500:
            output[name] = value[:497] + "..."
        else:
            output[name] = value
    return output


def _summarize_result(result: Any) -> Dict[str, Any]:
    if isinstance(result, dict):
        summary: Dict[str, Any] = {"type": "object", "keys": sorted(str(key) for key in result)[:30]}
        for key in ("hits", "rows", "records", "items", "evidence"):
            value = result.get(key)
            if isinstance(value, list):
                summary[f"{key}_count"] = len(value)
            elif key == "evidence" and isinstance(value, dict):
                summary["evidence_count"] = 1
        if result.get("error"):
            summary["error"] = str(result.get("error"))[:500]
        return summary
    if isinstance(result, list):
        return {"type": "array", "count": len(result)}
    return {"type": type(result).__name__}


def _extract_evidence_ids(value: Any) -> List[str]:
    found: List[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            evidence_id = item.get("evidence_id") or item.get("result_id") or item.get("sample_id")
            if evidence_id and str(evidence_id) not in found:
                found.append(str(evidence_id))
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return found[:100]


def _json_preview(payload: Any, max_chars: int) -> str:
    text = json.dumps(payload, ensure_ascii=False, default=str)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 18].rstrip() + "\n...[truncated]"
