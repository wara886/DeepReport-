"""Record normalization helpers for unified manifest schema."""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List


MANIFEST_FIELDS = [
    "sample_id",
    "source_type",
    "symbol",
    "period",
    "title",
    "publish_time",
    "content",
    "source_url",
    "trust_level",
]


def _stable_sample_id(source_type: str, title: str, publish_time: str, source_url: str) -> str:
    raw = f"{source_type}|{title}|{publish_time}|{source_url}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _validate_required_fields(record: Dict[str, Any], required_fields: List[str], source_type: str) -> None:
    missing = [field for field in required_fields if not str(record.get(field, "")).strip()]
    if missing:
        raise ValueError(f"{source_type} record missing required fields: {', '.join(missing)}")


def normalize_record(record: Dict[str, Any], source_type: str, strict_required: bool = False) -> Dict[str, Any]:
    title = str(record.get("title", "")).strip()
    publish_time = str(record.get("publish_time", "")).strip()
    source_url = str(record.get("source_url", "")).strip()

    normalized = {
        "sample_id": record.get("sample_id") or _stable_sample_id(source_type, title, publish_time, source_url),
        "source_type": source_type,
        "symbol": str(record.get("symbol", "")).strip(),
        "period": str(record.get("period", "")).strip(),
        "title": title,
        "publish_time": publish_time,
        "content": str(record.get("content", "")).strip(),
        "source_url": source_url,
        "trust_level": str(record.get("trust_level", "medium")).strip() or "medium",
    }
    if strict_required:
        _validate_required_fields(
            normalized,
            required_fields=[
                "source_type",
                "symbol",
                "period",
                "title",
                "publish_time",
                "content",
                "source_url",
                "trust_level",
            ],
            source_type=source_type,
        )
    return normalized


def normalize_records(records: List[Dict[str, Any]], source_type: str, strict_required: bool = False) -> List[Dict[str, Any]]:
    return [normalize_record(item, source_type=source_type, strict_required=strict_required) for item in records]
