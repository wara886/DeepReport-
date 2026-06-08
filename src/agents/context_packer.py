"""Controllable prompt context packers for multi-agent report generation."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple


TRUST_WEIGHT = {
    "high": 3.0,
    "medium": 2.0,
    "low": 1.0,
}


def pack_claims(
    claims: List[Dict[str, Any]],
    max_items: int = 12,
    text_limit: int = 280,
    total_chars: int = 2800,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Trim and rank claims so prompts stay stable and auditable.

    Guarantees at least one claim per section (diversity), then fills remaining
    budget with highest-confidence claims from well-covered sections.
    """

    normalized = [_normalize_claim(item, text_limit=text_limit) for item in claims if isinstance(item, dict)]

    # Phase 1: group by section, pick highest-confidence claim from each
    by_section: Dict[str, List[Dict[str, Any]]] = {}
    for c in normalized:
        section = c.get("section_name", "")
        if section:
            by_section.setdefault(section, []).append(c)

    guaranteed: List[Dict[str, Any]] = []
    remaining: List[Dict[str, Any]] = []
    for section, section_claims in by_section.items():
        section_claims.sort(
            key=lambda c: (
                float(c.get("confidence", 0.0)),
                len(c.get("evidence_ids", [])),
                len(c.get("numeric_values", {})),
            ),
            reverse=True,
        )
        guaranteed.append(section_claims[0])
        remaining.extend(section_claims[1:])

    # Phase 2: sort remaining by confidence (full sort, not per-section)
    remaining.sort(
        key=lambda c: (
            float(c.get("confidence", 0.0)),
            len(c.get("evidence_ids", [])),
            len(c.get("numeric_values", {})),
        ),
        reverse=True,
    )

    # Phase 3: pack guaranteed first (high priority), then fill with remaining
    ordered = guaranteed + remaining
    packed, used_chars, dropped = _pack_with_char_budget(ordered, max_items=max_items, total_chars=total_chars)
    packed_ids = [str(item.get("claim_id", "")) for item in packed if str(item.get("claim_id", ""))]
    dropped_ids = [str(item.get("claim_id", "")) for item in dropped if str(item.get("claim_id", ""))]
    return packed, {
        "input_count": len(claims),
        "packed_count": len(packed),
        "dropped_count": len(dropped),
        "packed_ids": packed_ids,
        "dropped_ids": dropped_ids,
        "used_chars": used_chars,
        "total_chars": total_chars,
    }


def pack_evidence_records(
    records: List[Dict[str, Any]],
    prioritized_evidence_ids: List[str] | None = None,
    max_items: int = 12,
    content_limit: int = 600,
    total_chars: int = 5200,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Pack evidence with explicit budgeting and priority for cited records."""

    priorities = {str(item): index for index, item in enumerate(prioritized_evidence_ids or [])}
    normalized = []
    for item in records:
        if not isinstance(item, dict):
            continue
        normalized.append(_normalize_evidence_record(item, content_limit=content_limit, priorities=priorities))

    normalized.sort(
        key=lambda item: (
            int(item.get("_is_prioritized", 0)),
            int(item.get("_priority_order", 10_000)) * -1,
            float(item.get("_support_score", 0.0)),
            TRUST_WEIGHT.get(str(item.get("trust_level", "")).lower(), 0.0),
            float(item.get("score", 0.0)),
        ),
        reverse=True,
    )
    packed, used_chars, dropped = _pack_with_char_budget(normalized, max_items=max_items, total_chars=total_chars)
    packed_ids = [str(item.get("evidence_id", "")) for item in packed if str(item.get("evidence_id", ""))]
    dropped_ids = [str(item.get("evidence_id", "")) for item in dropped if str(item.get("evidence_id", ""))]
    prioritized_ids = [str(item) for item in prioritized_evidence_ids or []]
    prioritized_dropped_ids = [evidence_id for evidence_id in prioritized_ids if evidence_id and evidence_id in set(dropped_ids)]
    for item in packed:
        item.pop("_is_prioritized", None)
        item.pop("_priority_order", None)
        item.pop("_support_score", None)
    return packed, {
        "input_count": len(records),
        "packed_count": len(packed),
        "dropped_count": len(dropped),
        "packed_ids": packed_ids,
        "dropped_ids": dropped_ids[:20],
        "used_chars": used_chars,
        "total_chars": total_chars,
        "prioritized_evidence_count": len(priorities),
        "prioritized_dropped_ids": prioritized_dropped_ids[:20],
    }


def pack_markdown_excerpt(markdown: str, max_chars: int = 2200) -> str:
    cleaned = str(markdown or "").strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 12].rstrip() + "\n...[truncated]"


def build_revision_brief(
    verification_report: Dict[str, Any] | None,
    max_items: int = 8,
    item_char_limit: int = 220,
) -> str:
    """Compress verifier feedback into revision-ready instructions."""

    if not isinstance(verification_report, dict):
        return ""

    lines: List[str] = []
    for label, key in [
        ("Errors", "errors"),
        ("Warnings", "warnings"),
        ("Fix recommendations", "fix_recommendations"),
        ("LLM warnings", "llm_warnings"),
        ("LLM errors", "llm_errors"),
    ]:
        raw_items = verification_report.get(key, [])
        if not isinstance(raw_items, list):
            continue
        for item in raw_items:
            text = str(item).strip().replace("\n", " ")
            if not text:
                continue
            lines.append(f"{label}: {text[:item_char_limit]}")
            if len(lines) >= max_items:
                return "\n".join(f"- {line}" for line in lines)
    return "\n".join(f"- {line}" for line in lines)


def _normalize_claim(item: Dict[str, Any], text_limit: int) -> Dict[str, Any]:
    evidence_ids = item.get("evidence_ids", [])
    numeric_values = item.get("numeric_values", {})
    row = {
        "claim_id": str(item.get("claim_id", "")).strip(),
        "section_name": str(item.get("section_name", "")).strip(),
        "claim_text": str(item.get("claim_text", "")).replace("\n", " ").strip()[:text_limit],
        "evidence_ids": [str(evidence_id) for evidence_id in evidence_ids[:8]]
        if isinstance(evidence_ids, list)
        else [],
        "confidence": float(item.get("confidence", 0.0) or 0.0),
        "risk_level": str(item.get("risk_level", "")).strip(),
        "notes": str(item.get("notes", "")).replace("\n", " ").strip()[:160],
    }
    if isinstance(numeric_values, dict):
        row["numeric_values"] = {str(key): float(value) for key, value in list(numeric_values.items())[:8]}
    else:
        row["numeric_values"] = {}
    return row


def _normalize_evidence_record(
    item: Dict[str, Any],
    content_limit: int,
    priorities: Dict[str, int],
) -> Dict[str, Any]:
    evidence_id = str(item.get("evidence_id") or item.get("sample_id") or "").strip()
    content = str(item.get("content", "")).replace("\n", " ").strip()
    key_points = item.get("key_points", [])
    metadata = item.get("metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}
    compact_metadata = {
        key: metadata[key]
        for key in (
            "supported_claim_count",
            "source_period",
            "period_fallback",
            "filing_type",
            "accession_number",
            "page",
            "section",
        )
        if key in metadata
    }
    row = {
        "evidence_id": evidence_id,
        "title": str(item.get("title", "")).strip()[:180],
        "source_url": str(item.get("source_url", "")).strip(),
        "source_type": str(item.get("source_type", "")).strip(),
        "trust_level": str(item.get("trust_level", "")).strip(),
        "symbol": str(item.get("symbol", "")).strip(),
        "period": str(item.get("period", "")).strip(),
        "publish_time": str(item.get("publish_time", "")).strip(),
        "content": content[:content_limit],
        "key_points": [str(point).strip()[:120] for point in key_points[:3]]
        if isinstance(key_points, list)
        else [],
        "metadata": compact_metadata,
    }
    priority_order = priorities.get(evidence_id, 10_000)
    row["_is_prioritized"] = 1 if priority_order != 10_000 else 0
    row["_priority_order"] = priority_order
    row["_support_score"] = float(metadata.get("supported_claim_count", 0.0) or 0.0)
    row["score"] = float(item.get("rerank_score", item.get("score", 0.0)) or 0.0)
    return row


def _pack_with_char_budget(
    items: List[Dict[str, Any]],
    max_items: int,
    total_chars: int,
) -> Tuple[List[Dict[str, Any]], int, List[Dict[str, Any]]]:
    packed: List[Dict[str, Any]] = []
    dropped: List[Dict[str, Any]] = []
    used_chars = 0
    for index, item in enumerate(items):
        if len(packed) >= max_items:
            dropped.extend(items[index:])
            break
        candidate_chars = len(json.dumps(item, ensure_ascii=False))
        if packed and used_chars + candidate_chars > total_chars:
            dropped.extend(items[index:])
            break
        packed.append(item)
        used_chars += candidate_chars
    return packed, used_chars, dropped
