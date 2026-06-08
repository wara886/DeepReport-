"""Local evidence store built from curated parquet files."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from src.data.source_quality import apply_source_quality


@dataclass
class EvidenceRecord:
    sample_id: str
    source_type: str
    symbol: str
    period: str
    title: str
    publish_time: str
    content: str
    source_url: str
    trust_level: str
    evidence_id: str = ""
    source_timestamp: str = ""
    data_cutoff: str = ""
    freshness_days: int | None = None
    freshness_bucket: str = ""
    evidence_scope: str = ""
    source_authority: str = ""
    authority_level: str = ""
    source_document_type: str = ""
    authority_score: float = 0.0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvidenceRecord":
        annotated = apply_source_quality(dict(data))
        return cls(
            sample_id=str(annotated.get("sample_id", annotated.get("evidence_id", ""))),
            source_type=str(annotated.get("source_type", "")),
            symbol=str(annotated.get("symbol", "")),
            period=str(annotated.get("period", "")),
            title=str(annotated.get("title", "")),
            publish_time=str(annotated.get("publish_time", "")),
            content=str(annotated.get("content", "")),
            source_url=str(annotated.get("source_url", "")),
            trust_level=str(annotated.get("trust_level", "")),
            evidence_id=str(annotated.get("evidence_id", annotated.get("sample_id", ""))),
            source_timestamp=str(annotated.get("source_timestamp", "")),
            data_cutoff=str(annotated.get("data_cutoff", "")),
            freshness_days=annotated.get("freshness_days") if isinstance(annotated.get("freshness_days"), int) else None,
            freshness_bucket=str(annotated.get("freshness_bucket", "")),
            evidence_scope=str(annotated.get("evidence_scope", "")),
            source_authority=str(annotated.get("source_authority", "")),
            authority_level=str(annotated.get("authority_level", "")),
            source_document_type=str(annotated.get("source_document_type", "")),
            authority_score=float(annotated.get("authority_score", 0.0) or 0.0),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence_id": self.evidence_id or self.sample_id,
            "sample_id": self.sample_id,
            "source_type": self.source_type,
            "symbol": self.symbol,
            "period": self.period,
            "title": self.title,
            "publish_time": self.publish_time,
            "content": self.content,
            "source_url": self.source_url,
            "trust_level": self.trust_level,
            "source_timestamp": self.source_timestamp,
            "data_cutoff": self.data_cutoff,
            "freshness_days": self.freshness_days,
            "freshness_bucket": self.freshness_bucket,
            "evidence_scope": self.evidence_scope,
            "source_authority": self.source_authority,
            "authority_level": self.authority_level,
            "source_document_type": self.source_document_type,
            "authority_score": self.authority_score,
        }

    @property
    def searchable_text(self) -> str:
        return f"{self.title} {self.content}".strip()


class EvidenceStore:
    """In-memory evidence store for retrieval modules."""

    def __init__(self, records: List[EvidenceRecord], load_meta: Dict[str, Any] | None = None):
        self.records = records
        self.load_meta = load_meta or {}

    @classmethod
    def from_curated_parquet(cls, curated_dir: str | Path = "data/curated") -> "EvidenceStore":
        curated_path = Path(curated_dir)
        paths = sorted(curated_path.glob("*.parquet"))
        fallback_paths = sorted(list(curated_path.glob("*.json")) + list(curated_path.glob("*.jsonl")))
        if not paths:
            records, fallback_meta = _load_json_records(fallback_paths)
            return cls(
                records=[EvidenceRecord.from_dict(item) for item in records],
                load_meta={
                    "curated_dir": str(curated_path),
                    "file_count": len(fallback_paths),
                    "loaded_file_count": fallback_meta["loaded_file_count"],
                    "skipped_files": fallback_meta["skipped_files"],
                    "load_errors": fallback_meta["load_errors"],
                    "fallback_json_file_count": fallback_meta["loaded_file_count"],
                },
            )

        frames = []
        skipped_files: List[str] = []
        load_errors: List[Dict[str, str]] = []
        for path in paths:
            try:
                frames.append(pd.read_parquet(path))
            except Exception as exc:
                skipped_files.append(str(path))
                load_errors.append({"path": str(path), "error": str(exc), "error_type": _classify_load_error(exc)})
        fallback_records, fallback_meta = _load_json_records(fallback_paths)
        if not frames and not fallback_records:
            return cls(
                records=[],
                load_meta={
                    "curated_dir": str(curated_path),
                    "file_count": len(paths) + len(fallback_paths),
                    "loaded_file_count": 0,
                    "skipped_files": skipped_files + fallback_meta["skipped_files"],
                    "load_errors": load_errors + fallback_meta["load_errors"],
                },
            )
        records: List[EvidenceRecord] = []
        if frames:
            merged = pd.concat(frames, ignore_index=True)
            records.extend(EvidenceRecord.from_dict(dict(row)) for _, row in merged.iterrows())
        records.extend(EvidenceRecord.from_dict(item) for item in fallback_records)
        return cls(
            records=records,
            load_meta={
                "curated_dir": str(curated_path),
                "file_count": len(paths) + len(fallback_paths),
                "loaded_file_count": len(frames) + fallback_meta["loaded_file_count"],
                "skipped_files": skipped_files + fallback_meta["skipped_files"],
                "load_errors": load_errors + fallback_meta["load_errors"],
                "fallback_json_file_count": fallback_meta["loaded_file_count"],
            },
        )

    def filter(self, symbol: str | None = None, period: str | None = None) -> List[EvidenceRecord]:
        output = self.records
        if symbol:
            output = [r for r in output if r.symbol == symbol]
        if period:
            output = [r for r in output if r.period == period]
        return output


def _load_json_records(paths: List[Path]) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    skipped_files: List[str] = []
    load_errors: List[Dict[str, str]] = []
    loaded = 0
    for path in paths:
        try:
            if path.suffix.lower() == ".jsonl":
                rows = []
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        item = json.loads(line)
                        if isinstance(item, dict):
                            rows.append(item)
            else:
                parsed = json.loads(path.read_text(encoding="utf-8"))
                rows = parsed if isinstance(parsed, list) else parsed.get("records", []) if isinstance(parsed, dict) else []
                rows = [item for item in rows if isinstance(item, dict)]
            records.extend(rows)
            loaded += 1
        except Exception as exc:
            skipped_files.append(str(path))
            load_errors.append({"path": str(path), "error": str(exc)})
    return records, {"loaded_file_count": loaded, "skipped_files": skipped_files, "load_errors": load_errors}


def _classify_load_error(exc: Exception) -> str:
    text = str(exc).lower()
    if "repetition level histogram" in text or "parquet" in text:
        return "parquet_corrupt_or_incompatible"
    return exc.__class__.__name__
