"""Evidence chunking utilities for paragraph, table-row, and metric-level retrieval."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import re
from typing import Any, Dict, Iterable, List

from src.schemas.runtime_contracts import normalize_evidence_record


NUMERIC_RE = re.compile(
    r"(?P<label>[A-Za-z][A-Za-z /_-]{1,48}?)\s*(?:=|:|was|were|of)?\s*"
    r"(?P<value>-?\d+(?:\.\d+)?)\s*(?P<unit>B|M|%|x|times|billion|million)?",
    re.IGNORECASE,
)

METRIC_FIELD_NAMES = {
    "revenue_billion",
    "revenue_growth_pct",
    "gross_margin_pct",
    "net_margin_pct",
    "roe_pct",
    "roa_pct",
    "operating_cash_flow_billion",
    "free_cash_flow_billion",
    "close",
    "volume",
}


@dataclass
class EvidenceChunk:
    """Retrieval-compatible chunk with source lineage and numeric metadata."""

    chunk_id: str
    parent_sample_id: str
    source_type: str
    symbol: str
    period: str
    title: str
    publish_time: str
    content: str
    source_url: str
    trust_level: str
    chunk_type: str
    chunk_index: int
    page: int | None = None
    table_id: str = ""
    row_id: str = ""
    cell_refs: List[str] = field(default_factory=list)
    metric_name: str = ""
    numeric_values: Dict[str, float] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def sample_id(self) -> str:
        return self.chunk_id

    @property
    def searchable_text(self) -> str:
        metric_text = " ".join([self.metric_name, " ".join(self.numeric_values.keys())]).strip()
        section_prefix = "[{}]".format(self.title) if self.title else ""
        return f"{section_prefix} {self.source_type} {self.chunk_type} {metric_text} {self.content}".strip()

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "sample_id": self.chunk_id,
            "evidence_id": self.chunk_id,
            "chunk_id": self.chunk_id,
            "parent_sample_id": self.parent_sample_id,
            "parent_evidence_id": self.parent_sample_id,
            "source_type": self.source_type,
            "symbol": self.symbol,
            "period": self.period,
            "title": self.title,
            "publish_time": self.publish_time,
            "content": self.content,
            "source_url": self.source_url,
            "trust_level": self.trust_level,
            "chunk_type": self.chunk_type,
            "chunk_index": self.chunk_index,
            "page": self.page,
            "table_id": self.table_id,
            "row_id": self.row_id,
            "cell_refs": list(self.cell_refs),
            "metric_name": self.metric_name,
            "numeric_values": dict(self.numeric_values),
            "metadata": dict(self.metadata),
        }
        target_period = str(payload["metadata"].get("target_period") or self.period)
        return normalize_evidence_record(payload, target_period=target_period)


def chunk_records(records: Iterable[Any], max_chars: int = 650) -> List[EvidenceChunk]:
    chunks: List[EvidenceChunk] = []
    for record in records:
        chunks.extend(chunk_record(record, max_chars=max_chars))
    return chunks


def chunk_record(record: Any, max_chars: int = 650) -> List[EvidenceChunk]:
    raw_data = _record_to_dict(record)
    data = normalize_evidence_record(raw_data)
    if _is_existing_chunk(raw_data):
        return [_existing_chunk(data)]
    parent_id = str(data.get("sample_id") or data.get("evidence_id") or _stable_id(data, "record"))
    source_type = str(data.get("source_type", ""))
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata"), dict) else {}
    chunks: List[EvidenceChunk] = []

    for index, text in enumerate(_split_paragraphs(str(data.get("content", "")), max_chars=max_chars), start=1):
        chunks.append(_make_chunk(data, parent_id, text, "paragraph", index, numeric_values=_extract_numeric_values(text)))

    table_chunks = _table_chunks_from_metadata(data, parent_id, metadata)
    chunks.extend(table_chunks)
    metric_chunks = _metric_chunks_from_metadata(data, parent_id, metadata)
    chunks.extend(metric_chunks)

    if not chunks:
        chunks.append(_make_chunk(data, parent_id, str(data.get("content", "")), "paragraph", 1))

    return _dedupe_chunks(chunks)


def _is_existing_chunk(data: Dict[str, Any]) -> bool:
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    chunking = metadata.get("chunking") if isinstance(metadata.get("chunking"), dict) else {}
    return bool(chunking.get("strategy") or data.get("chunk_id") or data.get("parent_sample_id"))


def _existing_chunk(data: Dict[str, Any]) -> EvidenceChunk:
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    chunking = metadata.get("chunking") if isinstance(metadata.get("chunking"), dict) else {}
    chunk_id = str(data.get("chunk_id") or data.get("sample_id") or data.get("evidence_id") or _stable_id(data, "chunk"))
    parent_id = str(
        data.get("parent_sample_id")
        or data.get("parent_evidence_id")
        or chunking.get("parent_sample_id")
        or chunk_id
    )
    chunk_type = str(data.get("chunk_type") or _chunk_type_from_id(chunk_id) or "paragraph")
    chunk_index = data.get("chunk_index")
    if chunk_index in (None, ""):
        match = re.search(rf"__{re.escape(chunk_type)}_(\d+)_chunk_", chunk_id)
        chunk_index = int(match.group(1)) if match else 1
    return EvidenceChunk(
        chunk_id=chunk_id,
        parent_sample_id=parent_id,
        source_type=str(data.get("source_type") or ""),
        symbol=str(data.get("symbol") or ""),
        period=str(data.get("period") or ""),
        title=str(data.get("title") or ""),
        publish_time=str(data.get("publish_time") or ""),
        content=str(data.get("content") or "").strip(),
        source_url=str(data.get("source_url") or ""),
        trust_level=str(data.get("trust_level") or ""),
        chunk_type=chunk_type,
        chunk_index=int(chunk_index),
        page=data.get("page") if isinstance(data.get("page"), int) else None,
        table_id=str(data.get("table_id") or ""),
        row_id=str(data.get("row_id") or ""),
        cell_refs=[str(item) for item in data.get("cell_refs", [])] if isinstance(data.get("cell_refs"), list) else [],
        metric_name=str(data.get("metric_name") or ""),
        numeric_values=_numeric_dict(data.get("numeric_values", {}))
        if isinstance(data.get("numeric_values"), dict)
        else {},
        metadata=dict(metadata),
    )


def _chunk_type_from_id(chunk_id: str) -> str:
    matches = re.findall(r"__(paragraph|table_row|metric)_\d+_chunk_", str(chunk_id or ""))
    return matches[-1] if matches else ""


def _make_chunk(
    data: Dict[str, Any],
    parent_id: str,
    content: str,
    chunk_type: str,
    chunk_index: int,
    metric_name: str = "",
    numeric_values: Dict[str, float] | None = None,
    table_id: str = "",
    row_id: str = "",
    cell_refs: List[str] | None = None,
) -> EvidenceChunk:
    metadata = data.get("metadata", {}) if isinstance(data.get("metadata"), dict) else {}
    page = data.get("page") or data.get("page_number")
    try:
        page_value = int(page) if page not in {None, ""} else None
    except (TypeError, ValueError):
        page_value = None
    digest = _stable_id(
        {
            "parent": parent_id,
            "chunk_type": chunk_type,
            "chunk_index": chunk_index,
            "metric_name": metric_name,
            "content": content,
        },
        "chunk",
    )
    return EvidenceChunk(
        chunk_id=f"{parent_id}__{chunk_type}_{chunk_index}_{digest}",
        parent_sample_id=parent_id,
        source_type=str(data.get("source_type", "")),
        symbol=str(data.get("symbol", "")),
        period=str(data.get("period", "")),
        title=str(data.get("title", "")),
        publish_time=str(data.get("publish_time", "")),
        content=str(content).strip(),
        source_url=str(data.get("source_url", "")),
        trust_level=str(data.get("trust_level", "")),
        chunk_type=chunk_type,
        chunk_index=chunk_index,
        page=page_value,
        table_id=table_id,
        row_id=row_id,
        cell_refs=cell_refs or [],
        metric_name=metric_name,
        numeric_values=numeric_values or {},
        metadata={
            "parent_metadata": metadata,
            "parent_identity_key": data.get("identity_key", ""),
            "document_key": data.get("document_key", ""),
            "target_period": (data.get("period_spec") or {}).get("target_period", data.get("period", "")),
            "period_match": (data.get("period_spec") or {}).get("match"),
            **{
                key: data.get(key, metadata.get(key))
                for key in ("source_period", "period_fallback")
                if data.get(key, metadata.get(key)) not in (None, "")
            },
            "chunking": {"strategy": "paragraph_table_metric_v1", "parent_sample_id": parent_id},
        },
    )


def _split_paragraphs(content: str, max_chars: int) -> List[str]:
    text = str(content or "").strip()
    if not text:
        return []
    raw_parts = [part.strip() for part in re.split(r"\n\s*\n|(?<=[.!?。！？])\s+", text) if part.strip()]
    chunks: List[str] = []
    current = ""
    for part in raw_parts:
        if not current:
            current = part
        elif len(current) + 1 + len(part) <= max_chars:
            current = f"{current} {part}"
        else:
            chunks.append(current)
            current = part
    if current:
        chunks.append(current)
    return chunks


def _metric_chunks_from_metadata(data: Dict[str, Any], parent_id: str, metadata: Dict[str, Any]) -> List[EvidenceChunk]:
    chunks: List[EvidenceChunk] = []
    index = 1
    for key in sorted(METRIC_FIELD_NAMES):
        if key not in metadata or metadata.get(key) in {None, ""}:
            continue
        value = _safe_float(metadata.get(key))
        if value is None:
            continue
        content = f"{data.get('symbol', '')} {data.get('period', '')} {key} = {value}."
        chunks.append(
            _make_chunk(
                data=data,
                parent_id=parent_id,
                content=content,
                chunk_type="metric",
                chunk_index=index,
                metric_name=key,
                numeric_values={key: value},
                table_id=str(metadata.get("table_id", "")),
                row_id=str(metadata.get("row_id", "")),
                cell_refs=[str(metadata.get("cell_ref", ""))] if metadata.get("cell_ref") else [],
            )
        )
        index += 1
    return chunks


def _table_chunks_from_metadata(data: Dict[str, Any], parent_id: str, metadata: Dict[str, Any]) -> List[EvidenceChunk]:
    table_rows = metadata.get("table_rows", [])
    if not isinstance(table_rows, list):
        return []
    chunks: List[EvidenceChunk] = []
    for index, row in enumerate(table_rows, start=1):
        if not isinstance(row, dict):
            continue
        numeric_values = {key: value for key, value in _numeric_dict(row).items()}
        content = "; ".join(f"{key}={value}" for key, value in row.items() if not _is_empty(value))
        chunks.append(
            _make_chunk(
                data=data,
                parent_id=parent_id,
                content=content,
                chunk_type="table_row",
                chunk_index=index,
                metric_name=str(row.get("metric") or row.get("metric_name") or ""),
                numeric_values=numeric_values,
                table_id=str(row.get("table_id") or metadata.get("table_id") or "table_1"),
                row_id=str(row.get("row_id") or index),
                cell_refs=[str(item) for item in row.get("cell_refs", [])] if isinstance(row.get("cell_refs"), list) else [],
            )
        )
    return chunks


def _extract_numeric_values(text: str) -> Dict[str, float]:
    output: Dict[str, float] = {}
    for match in NUMERIC_RE.finditer(text):
        label = "_".join(match.group("label").lower().strip().split())[:48]
        value = _safe_float(match.group("value"))
        if not label or value is None:
            continue
        unit = (match.group("unit") or "").lower()
        key = f"{label}_{unit}" if unit else label
        output[key] = value
    return output


def _numeric_dict(row: Dict[str, Any]) -> Dict[str, float]:
    output = {}
    for key, value in row.items():
        parsed = _safe_float(value)
        if parsed is not None:
            output[str(key)] = parsed
    return output


def _record_to_dict(record: Any) -> Dict[str, Any]:
    if isinstance(record, dict):
        return dict(record)
    if hasattr(record, "to_dict"):
        return dict(record.to_dict())
    return {}


def _dedupe_chunks(chunks: List[EvidenceChunk]) -> List[EvidenceChunk]:
    seen: set[str] = set()
    output: List[EvidenceChunk] = []
    for chunk in chunks:
        key = f"{chunk.chunk_type}|{chunk.metric_name}|{chunk.content}"
        if key in seen:
            continue
        seen.add(key)
        output.append(chunk)
    return output


def _stable_id(data: Dict[str, Any], prefix: str) -> str:
    raw = "|".join(f"{key}={data.get(key, '')}" for key in sorted(data.keys()))
    return f"{prefix}_{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:10]}"


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_empty(value: Any) -> bool:
    return value is None or value == ""
