"""OpenAI-compatible model adapter used by the Agent layer.

The first real backend is DeepSeek, whose API follows the ChatCompletions
message shape. The adapter intentionally stays dependency-light so the project
can run in the existing local environment before we add richer SDK support.
"""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List
from urllib import error, request

from src.utils.config import load_config
from src.utils.env import load_env_files, resolve_config_value


Message = Dict[str, Any]


@dataclass
class ModelResponse:
    """Normalized response returned by a chat model call."""

    success: bool
    content: str = ""
    model: str = ""
    usage: Dict[str, Any] | None = None
    raw: Dict[str, Any] | None = None
    tool_calls: List[Dict[str, Any]] | None = None
    reasoning_content: str = ""
    error: str = ""


class ModelAdapter:
    """Small OpenAI-compatible chat adapter for LLM agents."""

    def __init__(
        self,
        provider: str,
        model_name: str,
        base_url: str,
        api_key: str,
        timeout: float = 30.0,
        retry: int = 1,
        max_tokens: int = 4096,
        temperature: float = 0.2,
        extra_body: Dict[str, Any] | None = None,
    ):
        self.provider = provider
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = float(timeout)
        self.retry = int(max(0, retry))
        self.max_tokens = int(max_tokens)
        self.temperature = float(temperature)
        self.extra_body = dict(extra_body or {})

    @classmethod
    def from_config(
        cls,
        config_path: str | Path = "configs/model_backends.yaml",
        section: str = "agent_model",
        env_path: str | Path | None = None,
    ) -> "ModelAdapter":
        """Build an adapter from YAML config and local env variables."""

        config_path = Path(config_path)
        load_env_files(config_path=config_path, env_path=env_path)

        config = load_config(config_path)
        section_config = config.get(section)
        if not isinstance(section_config, dict):
            raise KeyError(f"Model config section not found: {section}")

        return cls(
            provider=str(section_config.get("provider", "openai_compatible")),
            model_name=str(resolve_config_value(section_config, "model_name", "deepseek-v4-flash")),
            base_url=str(resolve_config_value(section_config, "base_url", "https://api.deepseek.com")),
            api_key=str(resolve_config_value(section_config, "api_key", "")),
            timeout=float(section_config.get("timeout", 30)),
            retry=int(section_config.get("retry", 1)),
            max_tokens=int(resolve_config_value(section_config, "max_tokens", 4096)),
            temperature=float(resolve_config_value(section_config, "temperature", 0.2)),
            extra_body=dict(section_config.get("extra_body", {}) or {}),
        )

    @property
    def endpoint_url(self) -> str:
        """Return the normalized chat completion endpoint URL."""

        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"

    def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        response_format: Dict[str, Any] | None = None,
        extra_messages: List[Message] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """Generate one assistant response from a prompt."""

        messages: List[Message] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if extra_messages:
            messages.extend(extra_messages)
        messages.append({"role": "user", "content": prompt})
        return self.chat(messages=messages, response_format=response_format, **kwargs)

    def generate_json(
        self,
        prompt: str,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Generate and parse a JSON object response."""

        response = self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            response_format={"type": "json_object"},
            **kwargs,
        )
        if not response.success:
            raise RuntimeError(response.error)
        parsed = extract_json_object(response.content)
        if not isinstance(parsed, dict):
            raise RuntimeError("model response did not contain a JSON object")
        return parsed

    def chat(
        self,
        messages: List[Message],
        response_format: Dict[str, Any] | None = None,
        tools: List[Dict[str, Any]] | None = None,
        tool_choice: str | Dict[str, Any] | None = None,
        extra_body: Dict[str, Any] | None = None,
    ) -> ModelResponse:
        """Call an OpenAI-compatible chat completion endpoint."""

        if not self.api_key:
            return ModelResponse(
                success=False,
                model=self.model_name,
                error="missing API key: set DEEPSEEK_API_KEY in .env",
            )

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "stream": False,
        }
        if response_format:
            payload["response_format"] = response_format
        if tools:
            payload["tools"] = tools
        if tool_choice:
            payload["tool_choice"] = tool_choice
        if self.extra_body:
            payload.update(self.extra_body)
        if extra_body:
            payload.update(extra_body)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        last_error = ""
        for attempt in range(self.retry + 1):
            req = request.Request(self.endpoint_url, data=body, headers=headers, method="POST")
            try:
                with request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode("utf-8")
                parsed = json.loads(raw)
                return _normalize_chat_response(parsed, fallback_model=self.model_name)
            except (TimeoutError, socket.timeout):
                last_error = f"model call timed out on attempt {attempt + 1}"
            except error.HTTPError as exc:
                error_body = exc.read().decode("utf-8", errors="replace")
                last_error = f"HTTP {exc.code}: {error_body}"
            except (error.URLError, json.JSONDecodeError, RuntimeError) as exc:
                last_error = str(exc)

        return ModelResponse(success=False, model=self.model_name, error=last_error)


def _normalize_chat_response(payload: Dict[str, Any], fallback_model: str) -> ModelResponse:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("model response has no choices")

    first = choices[0]
    if not isinstance(first, dict):
        raise RuntimeError("model response choice is not an object")

    message = first.get("message")
    if not isinstance(message, dict):
        raise RuntimeError("model response has no assistant message")

    content = message.get("content") or ""
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)

    reasoning_content = message.get("reasoning_content") or ""
    if not isinstance(reasoning_content, str):
        reasoning_content = json.dumps(reasoning_content, ensure_ascii=False)

    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list):
        tool_calls = []

    usage = payload.get("usage")
    if not isinstance(usage, dict):
        usage = {}

    return ModelResponse(
        success=True,
        content=content,
        model=str(payload.get("model") or fallback_model),
        usage=usage,
        raw=payload,
        tool_calls=tool_calls,
        reasoning_content=reasoning_content,
    )


def extract_json_object(text: str) -> Any:
    """Extract JSON from a raw model response, including fenced code blocks."""

    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise
