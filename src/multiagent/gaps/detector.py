"""Convert verifier output into canonical structured gaps."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from src.multiagent.gaps.router import GapRouter, route_action_for_gap_type
from src.multiagent.gaps.schema import GapItem, GapSeverity, GapType


def gaps_from_verification_report(
    verification_report: Dict[str, Any],
    claims: List[Dict[str, Any]] | None = None,
    evidence_records: List[Dict[str, Any]] | None = None,
    detected_by: str = "VerifierAgent",
) -> List[Dict[str, Any]]:
    claims = claims or []
    evidence_records = evidence_records or []
    gaps: List[GapItem] = []
    context_by_gap_id: Dict[str, Dict[str, Any]] = {}

    for legacy in verification_report.get("evidence_gaps", []) if isinstance(verification_report.get("evidence_gaps", []), list) else []:
        if isinstance(legacy, dict):
            gap = _from_legacy_evidence_gap(legacy, detected_by=detected_by, index=len(gaps) + 1)
            gaps.append(gap)
            context_by_gap_id[gap.gap_id] = _conflict_context(
                legacy,
                claims=claims,
                evidence_records=evidence_records,
                related_claim_ids=gap.related_claim_ids,
                related_evidence_ids=gap.related_evidence_ids,
            )

    for message in _messages(verification_report):
        gap_type = infer_gap_type(message)
        if gap_type is None:
            continue
        claim_id = _claim_id(message)
        evidence_ids = _evidence_ids(message)
        section = _section_for_claim(claims, claim_id)
        gap = GapItem(
            gap_id=_stable_gap_id(len(gaps) + 1, gap_type, claim_id),
            gap_type=gap_type,
            severity=infer_severity(message, gap_type),
            detected_by=detected_by,
            related_claim_ids=[claim_id] if claim_id else [],
            related_evidence_ids=evidence_ids,
            section=section,
            description=message,
            recommended_action=route_action_for_gap_type(gap_type),
        )
        gaps.append(gap)
        context_by_gap_id[gap.gap_id] = _conflict_context(
            {"description": message},
            claims=claims,
            evidence_records=evidence_records,
            related_claim_ids=gap.related_claim_ids,
            related_evidence_ids=gap.related_evidence_ids,
        )

    deduped = _dedupe_gaps(gaps)
    routed = GapRouter().apply_routes(deduped)
    result = []
    for gap in routed:
        payload = gap.to_dict()
        context = context_by_gap_id.get(gap.gap_id, {})
        if context:
            payload.update(context)
        result.append(payload)
    return result


def infer_gap_type(message: str) -> GapType | None:
    text = str(message or "").lower()
    if "target symbol mismatch" in text or "period" in text or "entity" in text:
        return GapType.SYMBOL_PERIOD_MISMATCH
    if "source conflict" in text or "conflict" in text or "inconsistent source" in text:
        return GapType.SOURCE_CONFLICT
    if "valuation" in text or "dcf" in text or "p/e" in text or "p/s" in text or "multiple" in text:
        return GapType.VALUATION_GAP
    if "missing required header" in text or "empty placeholder" in text or "format" in text or "section" in text or "markdown" in text:
        return GapType.FORMAT_GAP
    if "numeric" in text or "number" in text or "not found in linked evidence" in text or "formula" in text:
        return GapType.NUMERIC_GAP
    if "not cited in markdown" in text or "missing evidence citations" in text or "citation" in text:
        return GapType.CITATION_GAP
    if "missing evidence ids" in text or "no primary evidence source" in text or "primary-source support" in text or "unsupported" in text:
        return GapType.EVIDENCE_GAP
    if "risk" in text and ("missing" in text or "placeholder" in text or "empty" in text):
        return GapType.RISK_GAP
    if "peer" in text or "同行" in text or "同业" in text:
        return GapType.PEER_GAP
    if "compliance" in text or "合规" in text or "disclosure" in text:
        return GapType.COMPLIANCE_GAP
    if "multimodal" in text or "chart" in text:
        return GapType.FORMAT_GAP
    return None


def infer_severity(message: str, gap_type: GapType) -> GapSeverity:
    text = str(message or "").lower()
    if gap_type in {GapType.SYMBOL_PERIOD_MISMATCH, GapType.SOURCE_CONFLICT}:
        return GapSeverity.CRITICAL
    if "error" in text or "failed" in text or gap_type in {GapType.EVIDENCE_GAP, GapType.NUMERIC_GAP, GapType.VALUATION_GAP}:
        return GapSeverity.HIGH
    if gap_type in {GapType.CITATION_GAP, GapType.COMPLIANCE_GAP, GapType.FORMAT_GAP}:
        return GapSeverity.MEDIUM
    return GapSeverity.LOW


def _from_legacy_evidence_gap(legacy: Dict[str, Any], detected_by: str, index: int) -> GapItem:
    gap_type = infer_gap_type(str(legacy.get("description", ""))) or _legacy_gap_type(str(legacy.get("gap_type", "")))
    claim_id = str(legacy.get("claim_id", ""))
    return GapItem(
        gap_id=str(legacy.get("gap_id") or _stable_gap_id(index, gap_type, claim_id)),
        gap_type=gap_type,
        severity=GapSeverity.HIGH if bool(legacy.get("blocking", True)) else GapSeverity.MEDIUM,
        detected_by=detected_by,
        related_claim_ids=[claim_id] if claim_id else [],
        related_evidence_ids=_str_list(legacy.get("related_evidence_ids", [])),
        section=str(legacy.get("section", "")),
        description=str(legacy.get("description", "")),
        recommended_action=route_action_for_gap_type(gap_type),
        status=legacy.get("status", "open"),  # type: ignore[arg-type]
    )


def _legacy_gap_type(value: str) -> GapType:
    mapping = {
        "missing_primary_evidence": GapType.EVIDENCE_GAP,
        "missing_evidence": GapType.EVIDENCE_GAP,
        "valuation_formula_error": GapType.VALUATION_GAP,
        "multimodal_conflict": GapType.FORMAT_GAP,
        "entity_or_period_mismatch": GapType.SYMBOL_PERIOD_MISMATCH,
    }
    return mapping.get(value, GapType.FORMAT_GAP)


def _messages(report: Dict[str, Any]) -> List[str]:
    messages: List[str] = []
    for key in ("errors", "warnings", "llm_errors", "llm_warnings"):
        value = report.get(key, [])
        if isinstance(value, list):
            messages.extend(str(item) for item in value if str(item).strip())
    return messages


def _conflict_context(
    source: Dict[str, Any],
    claims: List[Dict[str, Any]],
    evidence_records: List[Dict[str, Any]],
    related_claim_ids: List[str],
    related_evidence_ids: List[str],
) -> Dict[str, Any]:
    context: Dict[str, Any] = {}
    explicit_claims = source.get("conflicting_claims", [])
    if isinstance(explicit_claims, list) and explicit_claims:
        context["conflicting_claims"] = [item for item in explicit_claims if isinstance(item, dict)]
    else:
        matched_claims = _items_by_ids(claims, related_claim_ids, id_keys=("claim_id",))
        if len(matched_claims) >= 2:
            context["conflicting_claims"] = matched_claims

    explicit_evidence = source.get("conflicting_evidence", [])
    if isinstance(explicit_evidence, list) and explicit_evidence:
        context["conflicting_evidence"] = [item for item in explicit_evidence if isinstance(item, dict)]
    else:
        matched_evidence = _items_by_ids(evidence_records, related_evidence_ids, id_keys=("evidence_id", "sample_id"))
        if len(matched_evidence) >= 2:
            context["conflicting_evidence"] = matched_evidence

    return context


def _items_by_ids(items: List[Dict[str, Any]], ids: List[str], id_keys: tuple[str, ...]) -> List[Dict[str, Any]]:
    wanted = {str(item) for item in ids if str(item).strip()}
    if not wanted:
        return []
    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if any(str(item.get(key, "")) in wanted for key in id_keys):
            result.append(item)
    return result


def _claim_id(message: str) -> str:
    match = re.search(r"\bClaim\s+([A-Za-z0-9_-]+)", message)
    return match.group(1) if match else ""


def _evidence_ids(message: str) -> List[str]:
    if ":" not in message:
        return []
    tail = message.rsplit(":", 1)[-1]
    return [item.strip().strip(".,") for item in tail.split(",") if item.strip() and len(item.strip()) <= 80]


def _section_for_claim(claims: List[Dict[str, Any]], claim_id: str) -> str:
    if not claim_id:
        return ""
    for claim in claims:
        if isinstance(claim, dict) and str(claim.get("claim_id", "")) == claim_id:
            return str(claim.get("section_name", ""))
    return ""


def _stable_gap_id(index: int, gap_type: GapType, claim_id: str = "") -> str:
    suffix = f"_{claim_id}" if claim_id else ""
    return f"gap_{index:04d}_{gap_type.value.lower()}{suffix}"


def _dedupe_gaps(gaps: List[GapItem]) -> List[GapItem]:
    seen = set()
    result = []
    for gap in gaps:
        key = (gap.gap_type.value, tuple(gap.related_claim_ids), gap.description)
        if key in seen:
            continue
        seen.add(key)
        result.append(gap)
    return result


def _str_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]
