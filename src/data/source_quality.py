"""Source authority grading for financial evidence records."""

from __future__ import annotations

from typing import Any, Dict

from src.data.evidence_metadata import annotate_evidence_record
from src.data.source_authority import grade_source_authority


def apply_source_quality(record: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of an evidence/search record with authority metadata."""

    output = dict(record)
    grade = grade_source(record)
    for key in [
        "source_authority",
        "authority_level",
        "authority_score",
        "source_document_type",
        "allowed_claim_types",
    ]:
        output[key] = grade[key]
    output.setdefault("metadata", {})
    if isinstance(output["metadata"], dict):
        output["metadata"]["source_quality"] = grade
    if not str(output.get("trust_level", "")).strip():
        output["trust_level"] = grade["trust_level"]
    return annotate_evidence_record(output)


def grade_source(record: Dict[str, Any]) -> Dict[str, Any]:
    return grade_source_authority(record)
