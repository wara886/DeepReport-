"""Build claim-evidence bundles that bind each claim to its supporting evidence.

Each bundle pre-resolves evidence_ids to actual evidence content, classifies
grounding status, and marks whether the claim is allowed in the final report.
FinalAnswerAgent should only write ""grounded"" or ""partial"" claims.
"""

from __future__ import annotations

from typing import Any, Dict, List, Set


# Trust levels considered high-confidence for report inclusion
HIGH_TRUST_LEVELS = {"high", "official", "derived"}
LOW_TRUST_LEVELS = {"web_or_news", "low", "unknown"}


def build_claim_evidence_bundles(
    claims: List[Dict[str, Any]],
    evidence_records: List[Dict[str, Any]],
    derived_evidence: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Build bundles linking each claim to its supporting evidence.

    Args:
        claims: List of claim dicts, each with claim_id, claim_text, evidence_ids, etc.
        evidence_records: Standard evidence records from research phase.
        derived_evidence: Evidence records from internal model outputs.

    Returns:
        List of bundle dicts:
            {
                "claim_id": str,
                "section_name": str,
                "claim_text": str,
                "numeric_values": dict,
                "risk_level": str,
                "confidence": float,
                "supporting_evidence": [{"evidence_id", "content", "source_type", "trust_level"}, ...],
                "grounding_status": "grounded" | "partial" | "unverified",
                "allowed_in_report": bool,
            }
    """
    # Build lookup: evidence_id -> evidence record
    evidence_by_id: Dict[str, Dict[str, Any]] = {}
    for rec in evidence_records:
        if isinstance(rec, dict) and rec.get("evidence_id"):
            evidence_by_id[str(rec["evidence_id"])] = rec
    for rec in derived_evidence:
        if isinstance(rec, dict) and rec.get("evidence_id"):
            evidence_by_id[str(rec["evidence_id"])] = rec

    bundles: List[Dict[str, Any]] = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue

        claim_evidence_ids: Set[str] = set()
        raw_ids = claim.get("evidence_ids", [])
        if isinstance(raw_ids, list):
            for eid in raw_ids:
                if eid:
                    claim_evidence_ids.add(str(eid))

        # Resolve evidence content
        supporting: List[Dict[str, Any]] = []
        for eid in sorted(claim_evidence_ids):
            rec = evidence_by_id.get(eid)
            if rec:
                supporting.append({
                    "evidence_id": eid,
                    "content": str(rec.get("content", rec.get("title", ""))),
                    "source_type": str(rec.get("source_type", "unknown")),
                    "trust_level": str(rec.get("trust_level", "unknown")),
                })
            else:
                supporting.append({
                    "evidence_id": eid,
                    "content": "",
                    "source_type": "unknown",
                    "trust_level": "unknown",
                })

        # Determine grounding status
        grounding_status = _classify_grounding(supporting)

        bundles.append({
            "claim_id": str(claim.get("claim_id", "")),
            "section_name": str(claim.get("section_name", "")),
            "claim_text": str(claim.get("claim_text", "")),
            "numeric_values": dict(claim.get("numeric_values", {})) if isinstance(claim.get("numeric_values"), dict) else {},
            "risk_level": str(claim.get("risk_level", "unknown")),
            "confidence": float(claim.get("confidence", 0.0) or 0.0),
            "supporting_evidence": supporting,
            "grounding_status": grounding_status,
            "allowed_in_report": grounding_status in ("grounded", "partial"),
        })

    return bundles


def _classify_grounding(supporting: List[Dict[str, Any]]) -> str:
    """Classify a claim's grounding level based on its supporting evidence.

    - grounded: at least one high-trust evidence record (high/official/derived)
    - partial: only low-trust evidence or no direct trust_level match
    - unverified: no evidence_ids or all references are broken (empty content)
    """
    if not supporting:
        return "unverified"

    has_high = False
    has_content = False
    for ev in supporting:
        trust = str(ev.get("trust_level", "unknown")).lower()
        content = str(ev.get("content", "")).strip()
        if trust in HIGH_TRUST_LEVELS:
            has_high = True
        if content:
            has_content = True

    if not has_content:
        return "unverified"
    if has_high:
        return "grounded"
    return "partial"
