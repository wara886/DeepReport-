"""Frozen evidence snapshot construction for the formal benchmark.

The builder never fetches network data. It freezes only evidence records that
have already been staged under a source directory and records a content hash
for every benchmark case, including missing cases.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from src.utils.config import load_config


MANIFEST_FILENAME = "snapshot_manifest.json"
REQUIRED_EVIDENCE_FIELDS = (
    "evidence_id",
    "source_type",
    "title",
    "source_url",
    "publish_time",
    "content",
    "symbol",
    "period",
    "trust_level",
)


def load_formal_benchmark_config(config_path: str | Path) -> Dict[str, Any]:
    """Load the Phase 3 benchmark definition."""

    payload = load_config(config_path)
    benchmark = payload.get("benchmark", {}) if isinstance(payload.get("benchmark"), dict) else {}
    cases = benchmark.get("cases")
    variants = benchmark.get("variants")
    if not isinstance(cases, list) or not cases:
        raise ValueError("formal benchmark config must define cases")
    if not isinstance(variants, list) or {str(item.get("id")) for item in variants if isinstance(item, dict)} != {
        "direct_llm",
        "single_agent_rag",
        "multi_agent_rag",
    }:
        raise ValueError("formal benchmark config must define the three formal variants")
    if not str(benchmark.get("period") or "").strip():
        raise ValueError("formal benchmark config must define period")
    return benchmark


def build_frozen_snapshot(
    config_path: str | Path = "configs/benchmark_formal18_fy2024.yaml",
    source_root: str | Path | None = None,
    snapshot_root: str | Path | None = None,
) -> Dict[str, Any]:
    """Freeze pre-staged evidence records and write an auditable manifest."""

    benchmark = load_formal_benchmark_config(config_path)
    period = str(benchmark["period"])
    source = Path(source_root or benchmark.get("snapshot_source_root") or "data/benchmark_sources/fy2024")
    target = Path(snapshot_root or benchmark.get("snapshot_root") or "data/benchmarks/frozen_fy2024_v1")
    cases_root = target / "cases"
    cases_root.mkdir(parents=True, exist_ok=True)

    case_rows: List[Dict[str, Any]] = []
    for case in benchmark["cases"]:
        row = _freeze_case(dict(case), period=period, source_root=source, cases_root=cases_root)
        case_rows.append(row)

    missing = [row["case_id"] for row in case_rows if row["status"] != "ready"]
    snapshot_hash = _snapshot_sha256(case_rows, period=period)
    manifest = {
        "schema_version": "frozen_snapshot.v1",
        "dataset_version": str(benchmark.get("dataset_version") or benchmark.get("id") or ""),
        "benchmark_id": str(benchmark.get("id") or ""),
        "period": period,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_root": str(source),
        "snapshot_root": str(target),
        "offline_only": True,
        "snapshot_sha256": snapshot_hash,
        "case_count": len(case_rows),
        "ready_case_count": len(case_rows) - len(missing),
        "complete": not missing,
        "missing_or_invalid_cases": missing,
        "cases": case_rows,
    }
    target.mkdir(parents=True, exist_ok=True)
    (target / MANIFEST_FILENAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def validate_frozen_snapshot(
    snapshot_root: str | Path,
    require_complete: bool = True,
) -> Dict[str, Any]:
    """Validate manifest completeness and content hashes."""

    root = Path(snapshot_root)
    manifest_path = root / MANIFEST_FILENAME
    if not manifest_path.exists():
        raise FileNotFoundError(f"snapshot manifest not found: {manifest_path}")
    manifest = _read_dict(manifest_path)
    issues: List[str] = []
    for row in manifest.get("cases", []) if isinstance(manifest.get("cases"), list) else []:
        if not isinstance(row, dict) or row.get("status") != "ready":
            continue
        evidence_path = root / str(row.get("evidence_path") or "")
        if not evidence_path.exists():
            issues.append(f"{row.get('case_id')}: evidence file missing")
            continue
        if sha256_file(evidence_path) != str(row.get("sha256") or ""):
            issues.append(f"{row.get('case_id')}: sha256 mismatch")
    expected_snapshot_hash = _snapshot_sha256(
        [dict(row) for row in manifest.get("cases", []) if isinstance(row, dict)],
        period=str(manifest.get("period") or ""),
    )
    if expected_snapshot_hash != str(manifest.get("snapshot_sha256") or ""):
        issues.append("snapshot_sha256 mismatch")
    if require_complete and not bool(manifest.get("complete", False)):
        issues.append("snapshot is incomplete")
    return {**manifest, "valid": not issues, "validation_issues": issues}


def load_snapshot_case_evidence(snapshot_root: str | Path, case_id: str) -> List[Dict[str, Any]]:
    """Load frozen evidence for one ready case after hash validation."""

    validation = validate_frozen_snapshot(snapshot_root, require_complete=False)
    if not validation.get("valid"):
        raise ValueError("; ".join(validation.get("validation_issues", [])))
    match = next(
        (
            row
            for row in validation.get("cases", [])
            if isinstance(row, dict) and str(row.get("case_id") or "") == case_id
        ),
        None,
    )
    if not match or match.get("status") != "ready":
        return []
    path = Path(snapshot_root) / str(match["evidence_path"])
    return _read_jsonl(path)


def snapshot_evidence_ids(snapshot_root: str | Path, case_id: str) -> set[str]:
    """Return the evidence IDs allowed for formal traceability scoring."""

    return {
        str(row.get("evidence_id") or "")
        for row in load_snapshot_case_evidence(snapshot_root, case_id)
        if str(row.get("evidence_id") or "")
    }


def sha256_file(path: str | Path) -> str:
    """Compute a stable content hash."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _freeze_case(case: Dict[str, Any], period: str, source_root: Path, cases_root: Path) -> Dict[str, Any]:
    case_id = str(case.get("case_id") or "")
    symbol = str(case.get("canonical_symbol") or "")
    output_rel = Path("cases") / case_id / "evidence.jsonl"
    output_path = cases_root / case_id / "evidence.jsonl"
    source_path = _locate_source_file(source_root, case_id=case_id, symbol=symbol, period=period)
    base = {
        "case_id": case_id,
        "market": str(case.get("market") or ""),
        "company_name": str(case.get("company_name") or ""),
        "canonical_symbol": symbol,
        "period": period,
        "evidence_path": output_rel.as_posix(),
        "source_path": str(source_path) if source_path else "",
    }
    if source_path is None:
        output_path.unlink(missing_ok=True)
        return {**base, "status": "missing_source", "record_count": 0, "sha256": "", "issues": ["no staged evidence file"]}

    records = _read_evidence_file(source_path)
    normalized, issues = _normalize_records(records, symbol=symbol, period=period)
    if not normalized:
        output_path.unlink(missing_ok=True)
        return {**base, "status": "invalid_source", "record_count": 0, "sha256": "", "issues": issues or ["no valid FY2024 records"]}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in normalized) + "\n",
        encoding="utf-8",
    )
    return {
        **base,
        "status": "ready",
        "record_count": len(normalized),
        "sha256": sha256_file(output_path),
        "issues": issues,
    }


def _locate_source_file(source_root: Path, case_id: str, symbol: str, period: str) -> Path | None:
    candidates = [
        source_root / case_id / "evidence.jsonl",
        source_root / case_id / "evidence.json",
        source_root / symbol / period / "evidence.jsonl",
        source_root / symbol / period / "evidence.json",
    ]
    return next((path for path in candidates if path.exists()), None)


def _read_evidence_file(path: Path) -> List[Dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        return _read_jsonl(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"evidence JSON must contain a list: {path}")
    return [dict(row) for row in payload if isinstance(row, dict)]


def _normalize_records(records: Iterable[Dict[str, Any]], symbol: str, period: str) -> tuple[List[Dict[str, Any]], List[str]]:
    normalized: List[Dict[str, Any]] = []
    issues: List[str] = []
    for index, raw in enumerate(records, start=1):
        row = dict(raw)
        row.setdefault("evidence_id", row.get("sample_id", ""))
        row.setdefault("symbol", symbol)
        row.setdefault("period", period)
        missing = [field for field in REQUIRED_EVIDENCE_FIELDS if not str(row.get(field) or "").strip()]
        if missing:
            issues.append(f"record {index}: missing {', '.join(missing)}")
            continue
        if str(row["symbol"]).upper() != symbol.upper() or str(row["period"]).upper() != period.upper():
            issues.append(f"record {index}: symbol or period does not match frozen case")
            continue
        row["symbol"] = symbol
        row["period"] = period
        normalized.append(row)
    normalized.sort(key=lambda row: str(row.get("evidence_id") or ""))
    return normalized, issues


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(dict(value))
    return rows


def _read_dict(path: Path) -> Dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return dict(value) if isinstance(value, dict) else {}


def _snapshot_sha256(case_rows: List[Dict[str, Any]], period: str) -> str:
    payload = {
        "period": period,
        "cases": [
            {
                "case_id": str(row.get("case_id") or ""),
                "status": str(row.get("status") or ""),
                "record_count": int(row.get("record_count", 0) or 0),
                "sha256": str(row.get("sha256") or ""),
            }
            for row in sorted(case_rows, key=lambda item: str(item.get("case_id") or ""))
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
