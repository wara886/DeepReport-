"""Small ReAct/tool-calling loop shared by financial agents."""

from __future__ import annotations

import json
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
) -> Dict[str, Any]:
    """Let the model choose tools, execute them, and feed observations back."""

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    trace: List[Dict[str, Any]] = []
    observations: List[Dict[str, Any]] = []

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
                "final_content": response.content,
                "trace": trace,
                "observations": observations,
                "error": "",
            }

        messages.append(_assistant_tool_call_message(response))
        for call in tool_calls:
            tool_name, arguments = _parse_tool_call(call)
            call_id = str(call.get("id") or f"call_{step_index}_{len(trace) + 1}")
            if tool_name not in handlers:
                observation = {"error": f"unknown tool: {tool_name}"}
            else:
                try:
                    observation = handlers[tool_name](**arguments)
                except Exception as exc:
                    observation = {"error": str(exc)}

            observation_text = _json_preview(observation, max_chars=max_observation_chars)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": tool_name,
                    "content": observation_text,
                }
            )
            observations.append({"tool_name": tool_name, "arguments": arguments, "result": observation})
            trace.append(
                {
                    "step": step_index,
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "observation_preview": observation_text[:500],
                    "error": observation.get("error", "") if isinstance(observation, dict) else "",
                }
            )

    return {
        "success": True,
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


def _json_preview(payload: Any, max_chars: int) -> str:
    text = json.dumps(payload, ensure_ascii=False, default=str)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 18].rstrip() + "\n...[truncated]"
