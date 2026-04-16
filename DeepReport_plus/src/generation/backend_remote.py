"""Remote writer backend implementation."""

from __future__ import annotations

import json
import socket
from typing import Any, Dict
from urllib import error, request

from src.generation.backend_base import GenerationBackend


class RemoteGenerationBackend(GenerationBackend):
    def __init__(
        self,
        model_name: str,
        base_url: str,
        timeout: float = 10.0,
        retry: int = 1,
        max_tokens: int = 512,
        temperature: float = 0.2,
        api_key: str = "",
    ):
        self.model_name = model_name
        self.base_url = base_url
        self.timeout = float(timeout)
        self.retry = int(max(0, retry))
        self.max_tokens = int(max_tokens)
        self.temperature = float(temperature)
        self.api_key = api_key

    @property
    def name(self) -> str:
        return "remote"

    def generate_text(self, prompt: str, **kwargs: Any) -> str:
        if not self.base_url:
            raise RuntimeError("remote backend requires non-empty base_url")

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "prompt": prompt,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        if "plan" in kwargs:
            payload["plan"] = kwargs["plan"]
        if "claims" in kwargs:
            claim_rows = []
            for item in kwargs["claims"]:
                if hasattr(item, "to_dict"):
                    claim_rows.append(item.to_dict())
                elif isinstance(item, dict):
                    claim_rows.append(item)
            payload["claims"] = claim_rows

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        body = json.dumps(payload).encode("utf-8")
        req = request.Request(self.base_url, data=body, headers=headers, method="POST")

        last_err: Exception | None = None
        for attempt in range(self.retry + 1):
            try:
                with request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read().decode("utf-8")
                parsed = json.loads(raw)
                text = self._extract_text(parsed)
                if not text.strip():
                    raise RuntimeError("remote backend returned empty text")
                return text
            except (TimeoutError, socket.timeout):
                last_err = TimeoutError(f"remote backend timeout on attempt {attempt + 1}")
            except (error.HTTPError, error.URLError, json.JSONDecodeError, RuntimeError) as exc:
                last_err = exc

        raise RuntimeError(f"remote backend failed after retries: {last_err}")

    def generate_structured(
        self,
        prompt: str,
        schema: Dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        del schema
        text = self.generate_text(prompt=prompt, **kwargs)
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        return {"text": text}

    @staticmethod
    def _extract_text(payload: Dict[str, Any]) -> str:
        if "text" in payload and isinstance(payload["text"], str):
            return payload["text"]
        if "output_text" in payload and isinstance(payload["output_text"], str):
            return payload["output_text"]
        if isinstance(payload.get("choices"), list) and payload["choices"]:
            first = payload["choices"][0]
            if isinstance(first, dict):
                if isinstance(first.get("text"), str):
                    return first["text"]
                message = first.get("message")
                if isinstance(message, dict) and isinstance(message.get("content"), str):
                    return message["content"]
        data = payload.get("data")
        if isinstance(data, dict) and isinstance(data.get("text"), str):
            return data["text"]
        raise RuntimeError("unable to extract text from remote backend response")
