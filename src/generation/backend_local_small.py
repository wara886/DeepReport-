"""Local small-model backend placeholder for Stage 6."""

from __future__ import annotations

from typing import Any, Dict

from src.generation.backend_base import GenerationBackend


class LocalSmallGenerationBackend(GenerationBackend):
    def __init__(self, **_: Any):
        pass

    @property
    def name(self) -> str:
        return "local_small"

    def generate_text(self, prompt: str, **kwargs: Any) -> str:
        del prompt, kwargs
        # Stage 11B keeps this backend as a reserved interface only.
        raise RuntimeError("local_small backend is not connected in Stage 6 yet.")

    def generate_structured(
        self,
        prompt: str,
        schema: Dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        del prompt, schema, kwargs
        raise RuntimeError("local_small backend is not connected in Stage 6 yet.")
