"""Writer with template/backend modes and fallback debug output."""

from __future__ import annotations

from collections import defaultdict
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List

from src.generation.backend_local_small import LocalSmallGenerationBackend
from src.generation.backend_mock import MockGenerationBackend
from src.generation.backend_remote import RemoteGenerationBackend
from src.schemas.claim import ClaimItem
from src.utils.config import load_config


class Writer:
    """Render markdown report from claim table."""

    SUPPORTED_MODES = {"template_only", "backend_generate"}

    def __init__(
        self,
        mode: str = "template_only",
        backend: str = "mock",
        backend_config_path: str = "configs/model_backends.yaml",
        debug_output_path: str | None = None,
    ):
        self.mode = mode
        self.backend = backend
        self.backend_config_path = backend_config_path
        self.debug_output_path = debug_output_path
        self.last_debug: Dict[str, Any] = {}
        if self.mode not in self.SUPPORTED_MODES:
            raise ValueError(f"Unsupported writer mode: {self.mode}")

    def render_markdown(
        self,
        plan: List[dict],
        claims: List[ClaimItem],
        retrieval_hits: List[Dict[str, object]] | None = None,
        retrieval_meta: Dict[str, object] | None = None,
    ) -> str:
        start = time.perf_counter()
        fallback_triggered = False
        error_message = ""

        if self.mode == "backend_generate":
            try:
                backend_impl = self._resolve_backend(self.backend)
                output = backend_impl.generate_text(
                    prompt=self._build_prompt(plan),
                    plan=plan,
                    claims=claims,
                    retrieval_hits=(retrieval_hits or []),
                    retrieval_meta=(retrieval_meta or {}),
                )
                if output and output.strip():
                    output_with_context = self._append_retrieval_context(
                        markdown=output,
                        retrieval_hits=retrieval_hits or [],
                        retrieval_meta=retrieval_meta or {},
                    )
                    self._write_debug(
                        backend_mode=backend_impl.name,
                        generation_time=time.perf_counter() - start,
                        fallback_triggered=False,
                        section_count=len(plan),
                        error_message="",
                    )
                    return output_with_context
                fallback_triggered = True
                error_message = "backend returned empty content"
            except Exception as exc:
                fallback_triggered = True
                error_message = str(exc)

        if not error_message and fallback_triggered:
            error_message = "backend_generate fallback to template_only"

        markdown = self._render_template(
            plan=plan,
            claims=claims,
            retrieval_hits=(retrieval_hits or []),
            retrieval_meta=(retrieval_meta or {}),
        )
        self._write_debug(
            backend_mode=self.backend if self.mode == "backend_generate" else "template_only",
            generation_time=time.perf_counter() - start,
            fallback_triggered=fallback_triggered,
            section_count=len(plan),
            error_message=error_message,
        )
        return markdown

    def _resolve_backend(self, backend_name: str):
        backend_cfg = self._load_backend_config(backend_name)
        if backend_name == "mock":
            return MockGenerationBackend(**backend_cfg)
        if backend_name == "local_small":
            return LocalSmallGenerationBackend(**backend_cfg)
        if backend_name == "remote":
            return RemoteGenerationBackend(**backend_cfg)
        raise ValueError(f"Unsupported backend: {backend_name}")

    def _load_backend_config(self, backend_name: str) -> Dict[str, Any]:
        cfg = load_config(self.backend_config_path)
        writer_cfg = dict(cfg.get("writer_backend", {}))
        common_cfg = dict(writer_cfg.get("common", {}))
        backend_map = dict(writer_cfg.get("backends", {}))
        current_cfg = dict(backend_map.get(backend_name, {}))

        merged = {**common_cfg, **current_cfg}

        base_url_env = str(merged.get("base_url_env", "")).strip()
        api_key_env = str(merged.get("api_key_env", "")).strip()
        model_name_env = str(merged.get("model_name_env", "")).strip()

        if model_name_env and not str(merged.get("model_name", "")).strip():
            merged["model_name"] = os.getenv(model_name_env, "")
        if base_url_env and not str(merged.get("base_url", "")).strip():
            merged["base_url"] = os.getenv(base_url_env, "")
        if api_key_env and not str(merged.get("api_key", "")).strip():
            merged["api_key"] = os.getenv(api_key_env, "")

        return {
            "model_name": str(merged.get("model_name", "")),
            "timeout": float(merged.get("timeout", 10)),
            "retry": int(merged.get("retry", 1)),
            "max_tokens": int(merged.get("max_tokens", 512)),
            "temperature": float(merged.get("temperature", 0.2)),
            "base_url": str(merged.get("base_url", "")),
            "api_key": str(merged.get("api_key", "")),
        }

    def _build_prompt(self, plan: List[dict]) -> str:
        sections = [str(item.get("section_title", "")).strip() for item in plan]
        return "Write a concise company research report in markdown.\nSections: " + ", ".join(sections)

    def _write_debug(
        self,
        backend_mode: str,
        generation_time: float,
        fallback_triggered: bool,
        section_count: int,
        error_message: str,
    ) -> None:
        debug_payload = {
            "backend_mode": backend_mode,
            "generation_time": round(float(generation_time), 4),
            "fallback_triggered": bool(fallback_triggered),
            "section_count": int(section_count),
            "error_message": error_message,
        }
        self.last_debug = debug_payload
        if not self.debug_output_path:
            return

        path = Path(self.debug_output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(debug_payload, indent=2), encoding="utf-8")

    def _render_template(
        self,
        plan: List[dict],
        claims: List[ClaimItem],
        retrieval_hits: List[Dict[str, object]] | None = None,
        retrieval_meta: Dict[str, object] | None = None,
    ) -> str:
        by_section: Dict[str, List[ClaimItem]] = defaultdict(list)
        for claim in claims:
            by_section[claim.section_name].append(claim)

        lines: List[str] = []
        lines.append("# Company Research Report")
        lines.append("")
        lines.append("This report is generated by a claim-first Stage 4 pipeline.")
        lines.append("")

        for section in plan:
            name = section["section_name"]
            title = section["section_title"]
            lines.append(f"## {title}")
            lines.append("")

            section_claims = by_section.get(name, [])
            if not section_claims:
                lines.append("- No claims generated for this section in current sample.")
                lines.append("")
                continue

            for item in section_claims:
                lines.append(f"- {item.claim_text}")
                if item.evidence_ids:
                    lines.append(f"  - evidence_ids: {', '.join(item.evidence_ids)}")
                lines.append(f"  - confidence: {item.confidence:.2f}")
            lines.append("")

        return self._append_retrieval_context(
            markdown="\n".join(lines),
            retrieval_hits=(retrieval_hits or []),
            retrieval_meta=(retrieval_meta or {}),
        )

    def _append_retrieval_context(
        self,
        markdown: str,
        retrieval_hits: List[Dict[str, object]],
        retrieval_meta: Dict[str, object],
    ) -> str:
        if not retrieval_hits:
            return markdown

        lines = [markdown, "", "## Retrieval Highlights", ""]
        mode = str(retrieval_meta.get("mode", "bm25"))
        fallback = bool(retrieval_meta.get("fallback_used", False))
        lines.append(f"- ranking_mode: {mode}")
        lines.append(f"- fallback_used: {fallback}")
        lines.append("")
        for item in retrieval_hits[:3]:
            title = str(item.get("title", "Untitled")).strip() or "Untitled"
            score = float(item.get("rerank_score", item.get("score", 0.0)))
            lines.append(f"- {title} (score={score:.4f})")
        lines.append("")
        return "\n".join(lines)
