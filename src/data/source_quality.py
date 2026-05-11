"""Source authority grading for financial evidence records."""

from __future__ import annotations

from typing import Any, Dict

from src.data.source_authority import grade_source_authority


def apply_source_quality(record: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of an evidence/search record with authority metadata."""

    output = dict(record)
    grade = grade_source(record)
    output["source_authority"] = grade["source_authority"]
    output["authority_score"] = grade["authority_score"]
    output.setdefault("metadata", {})
    if isinstance(output["metadata"], dict):
        output["metadata"]["source_quality"] = grade
    if not str(output.get("trust_level", "")).strip():
        output["trust_level"] = grade["trust_level"]
    return output


def grade_source(record: Dict[str, Any]) -> Dict[str, Any]:
    return grade_source_authority(record)
