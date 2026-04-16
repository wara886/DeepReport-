"""Build and persist unified manifest outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pyarrow as pa
import pyarrow.parquet as pq

from src.data.dedup import deduplicate_records
from src.data.normalize import MANIFEST_FIELDS, normalize_records


def build_manifest(records: List[Dict[str, Any]], source_type: str, strict_required: bool = False) -> List[Dict[str, Any]]:
    normalized = normalize_records(records, source_type=source_type, strict_required=strict_required)
    deduped = deduplicate_records(normalized)
    return deduped


def write_manifest_parquet(records: List[Dict[str, Any]], output_path: str | Path) -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for item in records:
        rows.append({field: item.get(field, "") for field in MANIFEST_FIELDS})

    table = pa.Table.from_pylist(rows, schema=pa.schema([(field, pa.string()) for field in MANIFEST_FIELDS]))
    pq.write_table(table, out)
    return out


def write_manifest_json(records: List[Dict[str, Any]], output_path: str | Path) -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    return out
