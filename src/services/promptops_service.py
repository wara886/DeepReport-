"""PromptOps template/version management backed by the LLM Harness."""

from __future__ import annotations

from collections.abc import Callable
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from src.agents.verifier import Verifier
from src.db.models import PromptTemplate, PromptVersion
from src.generation.backend_mock import MockGenerationBackend
from src.llm.harness import LLMHarness
from src.schemas.claim import ClaimItem


class PromptTemplateNotFound(LookupError):
    """Raised when a prompt template cannot be found."""


class PromptOpsConflict(RuntimeError):
    """Raised when PromptOps input is invalid or conflicts."""


class PromptOpsService:
    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        harness_factory: Callable[..., LLMHarness] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.harness_factory = harness_factory

    def create_template(self, payload: dict[str, Any]) -> dict[str, Any]:
        prompt_key = _safe_key(payload.get("prompt_key") or payload.get("key"))
        name = _optional_string(payload.get("name")) or prompt_key
        content = _optional_string(payload.get("content"))
        with self.session_factory() as session:
            template = PromptTemplate(
                prompt_key=prompt_key,
                name=name,
                module=_optional_string(payload.get("module")) or "general",
                description=_optional_string(payload.get("description")),
                schema_json=_dict_or_none(payload.get("schema")),
                is_active=bool(payload.get("is_active", True)),
            )
            session.add(template)
            try:
                session.flush()
                if content:
                    template.versions.append(
                        PromptVersion(
                            template_id=template.id,
                            version=1,
                            content=content,
                            variables=_string_list(payload.get("variables")),
                            changelog=_optional_string(payload.get("changelog")) or "Initial version",
                            is_active=True,
                            metadata_json=_dict_or_none(payload.get("metadata")),
                        )
                    )
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise PromptOpsConflict(f"Prompt template already exists: {prompt_key}") from exc
            return self.get_template(prompt_key)

    def list_templates(self, *, module: str | None = None, active_only: bool = False, limit: int = 100) -> dict[str, Any]:
        limit = max(1, min(int(limit or 100), 300))
        with self.session_factory() as session:
            stmt = (
                select(PromptTemplate)
                .options(selectinload(PromptTemplate.versions))
                .order_by(PromptTemplate.created_at.desc(), PromptTemplate.id.desc())
                .limit(limit)
            )
            if module:
                stmt = stmt.where(PromptTemplate.module == module)
            if active_only:
                stmt = stmt.where(PromptTemplate.is_active.is_(True))
            items = [self.serialize_template(item) for item in session.scalars(stmt).unique().all()]
        return {"items": items, "total": len(items)}

    def get_template(self, template_ref: int | str) -> dict[str, Any]:
        with self.session_factory() as session:
            return self.serialize_template(_get_template(session, template_ref))

    def add_version(self, template_ref: int | str, payload: dict[str, Any]) -> dict[str, Any]:
        content = _optional_string(payload.get("content"))
        if not content:
            raise PromptOpsConflict("Prompt version content is required")
        with self.session_factory() as session:
            template = _get_template(session, template_ref)
            next_version = int(session.scalar(select(func.max(PromptVersion.version)).where(PromptVersion.template_id == template.id)) or 0) + 1
            version = PromptVersion(
                template_id=template.id,
                version=next_version,
                content=content,
                variables=_string_list(payload.get("variables")),
                changelog=_optional_string(payload.get("changelog")),
                is_active=bool(payload.get("is_active", True)),
                metadata_json=_dict_or_none(payload.get("metadata")),
            )
            if version.is_active:
                for item in template.versions:
                    item.is_active = False
            session.add(version)
            session.commit()
            return self.serialize_version(version)

    def set_active_version(self, template_ref: int | str, version_ref: int | str) -> dict[str, Any]:
        with self.session_factory() as session:
            template = _get_template(session, template_ref)
            version = _get_version(template, version_ref)
            for item in template.versions:
                item.is_active = item.id == version.id
            session.commit()
            return self.serialize_template(template)

    def set_template_active(self, template_ref: int | str, active: bool) -> dict[str, Any]:
        with self.session_factory() as session:
            template = _get_template(session, template_ref)
            template.is_active = bool(active)
            session.commit()
            return self.serialize_template(template)

    def resolve_active_version(self, prompt_key: str) -> dict[str, Any]:
        with self.session_factory() as session:
            template = _get_template(session, prompt_key)
            version = _active_version(template)
            if version is None:
                raise PromptTemplateNotFound(f"No active version for prompt: {prompt_key}")
            payload = self.serialize_version(version)
            payload["template"] = self.serialize_template(template, include_versions=False)
            return payload

    def test_prompt(self, prompt_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        active = self.resolve_active_version(prompt_key)
        template = active["template"]
        input_payload = _dict_or_none(payload.get("input")) or {}
        prompt = _render_prompt(active["content"], input_payload)
        backend = payload.get("backend") or _module_backend(prompt_key=prompt_key, module=template.get("module"), input_payload=input_payload)
        harness = self._harness(backend=backend)
        result = harness.run_prompt(
            prompt_key=prompt_key,
            input=input_payload,
            schema=template.get("schema") or None,
            model_role=_optional_string(payload.get("model_role")) or template.get("module"),
            task_id=_optional_string(payload.get("task_id")),
            prompt=prompt,
            prompt_version_id=active["id"],
            metadata={
                "source": "promptops_test",
                "module_binding": getattr(backend, "module_binding", None),
                "promptops_bound": True,
            },
        )
        return {
            "prompt_key": prompt_key,
            "prompt_version_id": active["id"],
            "rendered_prompt": prompt,
            "llm_run_id": result.run_id,
            "status": result.status,
            "output": result.output,
            "schema_valid": result.schema_valid,
            "fallback_used": result.fallback_used,
        }

    def serialize_template(self, item: PromptTemplate, *, include_versions: bool = True) -> dict[str, Any]:
        active = _active_version(item)
        payload = {
            "id": item.id,
            "prompt_key": item.prompt_key,
            "name": item.name,
            "module": item.module,
            "description": item.description,
            "schema": item.schema_json or {},
            "is_active": item.is_active,
            "active_version_id": active.id if active else None,
            "active_version": active.version if active else None,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }
        if include_versions:
            payload["versions"] = [self.serialize_version(version) for version in item.versions]
        return payload

    def serialize_version(self, item: PromptVersion) -> dict[str, Any]:
        return {
            "id": item.id,
            "template_id": item.template_id,
            "version": item.version,
            "content": item.content,
            "variables": item.variables or [],
            "changelog": item.changelog,
            "is_active": item.is_active,
            "metadata": item.metadata_json or {},
            "created_at": item.created_at.isoformat() if item.created_at else None,
        }

    def _harness(self, *, backend: Any | None) -> LLMHarness:
        if self.harness_factory:
            return self.harness_factory(backend=backend)
        return LLMHarness(session_factory=self.session_factory, backend=backend or MockGenerationBackend())


class ClaimVerifierPromptBackend:
    """Harness backend that binds PromptOps runs to the rule-based Claim Verifier."""

    name = "claim-verifier-rules"
    module_binding = "claim_verifier"

    def generate_structured(self, prompt: str, schema: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        del prompt, schema
        claims = [_claim_from_payload(item) for item in list(kwargs.get("claims") or []) if isinstance(item, dict)]
        markdown = str(kwargs.get("markdown") or "")
        evidence_records = [item for item in list(kwargs.get("evidence_records") or []) if isinstance(item, dict)]
        charts = [item for item in list(kwargs.get("charts") or []) if isinstance(item, dict)]
        tables = [item for item in list(kwargs.get("tables") or []) if isinstance(item, dict)]
        valuation = kwargs.get("valuation") if isinstance(kwargs.get("valuation"), dict) else None
        return Verifier().verify(
            claims=claims,
            markdown=markdown,
            evidence_records=evidence_records,
            charts=charts,
            tables=tables,
            valuation=valuation,
            expected_symbol=_optional_string(kwargs.get("expected_symbol")),
        )


def _get_template(session: Session, template_ref: int | str) -> PromptTemplate:
    text = str(template_ref).strip()
    condition = PromptTemplate.id == int(text) if text.isdigit() else PromptTemplate.prompt_key == text
    template = session.scalar(
        select(PromptTemplate)
        .where(condition)
        .options(selectinload(PromptTemplate.versions))
    )
    if template is None:
        raise PromptTemplateNotFound(text)
    return template


def _active_version(template: PromptTemplate) -> PromptVersion | None:
    active = [item for item in template.versions if item.is_active]
    if active:
        return sorted(active, key=lambda item: item.version, reverse=True)[0]
    return sorted(template.versions, key=lambda item: item.version, reverse=True)[0] if template.versions else None


def _get_version(template: PromptTemplate, version_ref: int | str) -> PromptVersion:
    text = str(version_ref).strip()
    for version in template.versions:
        if str(version.id) == text or str(version.version) == text:
            return version
    raise PromptTemplateNotFound(f"Prompt version not found: {version_ref}")


def _module_backend(*, prompt_key: str, module: str | None, input_payload: dict[str, Any]) -> Any | None:
    normalized_key = str(prompt_key or "").strip().lower()
    normalized_module = str(module or "").strip().lower()
    if normalized_key == "claim_verifier" and normalized_module in {"verifier", "claim_verifier"} and isinstance(input_payload.get("claims"), list):
        return ClaimVerifierPromptBackend()
    return None


def _claim_from_payload(payload: dict[str, Any]) -> ClaimItem:
    return ClaimItem.from_dict(
        {
            "claim_id": payload.get("claim_id") or payload.get("id") or "",
            "section_name": payload.get("section_name") or "financial_analysis",
            "claim_text": payload.get("claim_text") or payload.get("text") or "",
            "evidence_ids": payload.get("evidence_ids") or [],
            "numeric_values": payload.get("numeric_values") or {},
            "risk_level": payload.get("risk_level") or "unknown",
            "confidence": payload.get("confidence", 0.0),
            "notes": payload.get("notes") or "",
            "metric_lineage_ids": payload.get("metric_lineage_ids") or [],
            "input_metric_lineage_ids": payload.get("input_metric_lineage_ids") or [],
            "is_critical": payload.get("is_critical", False),
            "critical_claim_type": payload.get("critical_claim_type") or "",
        }
    )


def _render_prompt(content: str, values: dict[str, Any]) -> str:
    rendered = content
    for key, value in values.items():
        rendered = rendered.replace("{{" + str(key) + "}}", str(value))
    return rendered


def _safe_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9_.:-]+", "_", text).strip("_")
    if not text:
        raise PromptOpsConflict("prompt_key is required")
    return text


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in re.split(r"[,，\n]", str(value)) if part.strip()]


def _optional_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value).strip() or None


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None
