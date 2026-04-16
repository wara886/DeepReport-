"""Deduplication utilities for normalized records."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple


def _dedup_key(record: Dict[str, Any]) -> Tuple[str, str, str, str]:
    return (
        str(record.get("source_url", "")).strip().lower(),
        str(record.get("title", "")).strip().lower(),
        str(record.get("publish_time", "")).strip(),
        str(record.get("content", "")).strip()[:128].lower(),
    )


def deduplicate_records(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    output: List[Dict[str, Any]] = []
    for item in records:
        key = _dedup_key(item)
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output

