"""Adapters that normalize heterogeneous evidence chunks for retrieval."""

from __future__ import annotations

from typing import Any


SECTION_META_TAGS = {
    "business_overview": ["业务结构", "产品结构", "收入表现"],
    "management_discussion": ["收入表现", "利润质量", "经营波动", "现金流"],
    "financial_statements": ["收入表现", "利润质量", "现金流", "资产负债"],
    "risk_factors": ["风险披露", "竞争风险", "监管风险"],
    "ownership_governance": ["治理结构", "股东结构", "合规风险"],
    "shareholder_structure": ["股东结构", "治理结构"],
    "esg": ["ESG", "合规风险", "社会责任"],
}

CHUNK_TYPE_META_TAGS = {
    "table_row": ["表格结构化", "财务指标"],
    "metric": ["财务指标", "数值证据"],
    "paragraph": ["文本段落"],
    "figure": ["图片摘要"],
}


def normalize_retrieval_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return a metadata-rich retrieval record without changing source evidence semantics."""

    data = dict(record)
    if "text" in data and not data.get("content"):
        data["content"] = data.get("text")
    if "source_title" in data and not data.get("title"):
        data["title"] = data.get("source_title")
    if "chunk_id" in data and not data.get("sample_id"):
        data["sample_id"] = data.get("chunk_id")
    if "chunk_id" in data and not data.get("evidence_id"):
        data["evidence_id"] = data.get("chunk_id")
    if "block_type" in data and not data.get("chunk_type"):
        data["chunk_type"] = data.get("block_type")
    if "pages" in data and not data.get("page_no"):
        pages = _int_list(data.get("pages"))
        if pages:
            data["page_no"] = pages[0]
    if data.get("section_type") and not data.get("evidence_scope"):
        data["evidence_scope"] = data.get("section_type")
    data["meta_tags"] = _dedupe([
        *_str_list(data.get("meta_tags") or data.get("tags") or data.get("section_tags")),
        *SECTION_META_TAGS.get(str(data.get("section_type") or ""), []),
        *CHUNK_TYPE_META_TAGS.get(str(data.get("chunk_type") or data.get("block_type") or ""), []),
        *_content_tags(str(data.get("content") or data.get("text") or "")),
    ])
    metadata = dict(data.get("metadata") or {}) if isinstance(data.get("metadata"), dict) else {}
    for key in (
        "section_type",
        "section_title",
        "chunk_type",
        "page_no",
        "pages",
        "table_id",
        "row_id",
        "metric_name",
        "report_market",
        "anchor_source",
    ):
        if data.get(key) not in (None, "", []):
            metadata.setdefault(key, data.get(key))
    data["metadata"] = metadata
    return data


def normalize_retrieval_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [normalize_retrieval_record(record) for record in records if isinstance(record, dict)]


def _content_tags(text: str) -> list[str]:
    lowered = text.lower()
    rules = [
        ("收入表现", ("revenue", "sales", "收入", "营收")),
        ("利润质量", ("profit", "margin", "gross", "净利润", "毛利", "利润")),
        ("现金流", ("cash flow", "operating cash", "现金流")),
        ("资产负债", ("assets", "liabilities", "资产", "负债")),
        ("风险披露", ("risk", "风险")),
        ("监管风险", ("regulatory", "regulation", "政策", "监管")),
        ("需求波动", ("demand", "inventory", "渠道", "库存", "需求")),
    ]
    return [tag for tag, keywords in rules if any(keyword in lowered for keyword in keywords)]


def _int_list(value: Any) -> list[int]:
    values = value if isinstance(value, list) else [value]
    output: list[int] = []
    for item in values:
        try:
            output.append(int(item))
        except (TypeError, ValueError):
            continue
    return output


def _str_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    values = value if isinstance(value, list) else [value]
    return [str(item).strip() for item in values if str(item).strip()]


def _dedupe(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output
