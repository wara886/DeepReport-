"""Generation backend abstraction for writer backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List

from src.schemas.claim import ClaimItem


class GenerationBackend(ABC):
    """Abstract backend interface for report text generation."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Backend name."""

    @abstractmethod
    def generate_text(self, prompt: str, **kwargs: Any) -> str:
        """Generate free-form text from prompt."""

    @abstractmethod
    def generate_structured(
        self,
        prompt: str,
        schema: Dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Generate structured payload from prompt."""

    def generate_report(self, plan: List[dict], claims: List[ClaimItem]) -> str:
        """Backward-compatible report API used by Stage 6 smoke."""
        return self.generate_text(
            prompt="Generate a markdown company research report.",
            plan=plan,
            claims=claims,
        )
