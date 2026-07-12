"""Version contract for report run artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


ARTIFACT_FILES = {
    "evidence": ("output", "evidence.json"),
    "canonical_metrics": ("output", "canonical_metrics.json"),
    "claims": ("output", "claims.json"),
    "section_evidence_packs": ("output", "section_evidence_packs.json"),
    "citations": ("output", "citations.json"),
    "report": ("report", "report.md"),
    "section_verification": ("output", "section_verification.json"),
}

ARTIFACT_DEPENDENCIES = {
    "canonical_metrics": ("evidence",),
    "claims": ("evidence", "canonical_metrics"),
    "section_evidence_packs": ("evidence", "canonical_metrics", "claims"),
    "citations": ("evidence", "claims"),
    "report": ("evidence", "canonical_metrics", "claims", "section_evidence_packs", "citations"),
    "section_verification": ("report", "section_evidence_packs"),
}


def commit_run_artifacts(
    output_dir: str | Path,
    report_dir: str | Path,
    artifact_names: Iterable[str],
) -> dict[str, Any]:
    outputs = Path(output_dir)
    reports = Path(report_dir)
    manifest_path = outputs / "run_manifest.json"
    manifest = _read_manifest(manifest_path)
    artifacts = dict(manifest.get("artifacts") or {})
    for name in artifact_names:
        if name not in ARTIFACT_FILES:
            raise ValueError(f"Unknown run artifact: {name}")
        digest, paths = _artifact_digest(name, outputs=outputs, reports=reports)
        if not digest:
            continue
        dependencies = {
            dependency: str((artifacts.get(dependency) or {}).get("version") or "missing")
            for dependency in ARTIFACT_DEPENDENCIES.get(name, ())
        }
        artifacts[name] = {
            "version": digest[:16],
            "sha256": digest,
            "paths": paths,
            "dependencies": dependencies,
            "committed_at": datetime.now(timezone.utc).isoformat(),
        }
    manifest = _build_manifest(artifacts)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def validate_run_manifest(output_dir: str | Path, report_dir: str | Path) -> dict[str, Any]:
    outputs = Path(output_dir)
    reports = Path(report_dir)
    manifest_path = outputs / "run_manifest.json"
    manifest = _read_manifest(manifest_path)
    artifacts = dict(manifest.get("artifacts") or {})
    current_versions: dict[str, str] = {}
    missing_files: list[str] = []
    for name in artifacts:
        digest, _paths = _artifact_digest(name, outputs=outputs, reports=reports)
        current_versions[name] = digest[:16] if digest else "missing"
        if not digest:
            missing_files.append(name)
    stale: dict[str, list[str]] = {}
    for name, entry in artifacts.items():
        reasons: list[str] = []
        if current_versions.get(name) != str(entry.get("version") or "missing"):
            reasons.append("content_changed_without_commit")
        for dependency, expected_version in dict(entry.get("dependencies") or {}).items():
            actual_version = current_versions.get(dependency, "missing")
            if actual_version != expected_version:
                reasons.append(f"dependency_changed:{dependency}:{expected_version}->{actual_version}")
        if reasons:
            stale[name] = reasons
    result = {
        **manifest,
        "status": "stale" if stale or missing_files else "ready",
        "stale_artifacts": stale,
        "missing_artifacts": missing_files,
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def _build_manifest(artifacts: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "report_run_manifest.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "ready",
        "artifacts": artifacts,
        "stale_artifacts": {},
        "missing_artifacts": [],
    }


def _artifact_digest(name: str, *, outputs: Path, reports: Path) -> tuple[str, list[str]]:
    spec = ARTIFACT_FILES[name]
    root = outputs if spec[0] == "output" else reports
    paths = [root / filename for filename in spec[1:]]
    existing = [path for path in paths if path.is_file()]
    if not existing:
        return "", []
    digest = hashlib.sha256()
    relative_paths: list[str] = []
    for path in existing:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
        relative_paths.append(str(path))
    return digest.hexdigest(), relative_paths


def _read_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return _build_manifest({})
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _build_manifest({})
    return payload if isinstance(payload, dict) else _build_manifest({})
