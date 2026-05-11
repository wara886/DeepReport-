"""Structured evidence gaps emitted by verifier checks."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List


@dataclass
class EvidenceGap:
    gap_id: str
    gap_type: str
    description: str
    claim_id: str = ""
    required_source_type: List[str] = field(default_factory=list)
    required_fields: List[str] = field(default_factory=list)
    suggested_queries: List[str] = field(default_factory=list)
    blocking: bool = True
    status: str = "open"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gap_id": self.gap_id,
            "gap_type": self.gap_type,
            "description": self.description,
            "claim_id": self.claim_id,
            "required_source_type": list(self.required_source_type),
            "required_fields": list(self.required_fields),
            "suggested_queries": list(self.suggested_queries),
            "blocking": self.blocking,
            "status": self.status,
        }


def build_evidence_gaps(
    verification_report: Dict[str, Any],
    claims: List[Dict[str, Any]],
    expected_symbol: str = "",
    period: str = "",
) -> List[Dict[str, Any]]:
    """Convert verifier errors and warnings into routable gap objects."""

    gaps: List[EvidenceGap] = []
    messages = _messages(verification_report)
    for index, message in enumerate(messages, start=1):
        claim_id = _claim_id(message)
        gap_type = _gap_type(message)
        if gap_type == "unknown":
            continue
        gap = EvidenceGap(
            gap_id=f"gap_{index:04d}_{gap_type}",
            gap_type=gap_type,
            description=message,
            claim_id=claim_id,
            required_source_type=_required_sources(gap_type),
            required_fields=_required_fields(gap_type, message),
            suggested_queries=_suggested_queries(
                claim=_claim_by_id(claims, claim_id),
                symbol=expected_symbol,
                period=period,
                gap_type=gap_type,
            ),
            blocking=gap_type in {"missing_primary_evidence", "missing_evidence", "multimodal_conflict", "valuation_formula_error"},
        )
        gaps.append(gap)
    return [gap.to_dict() for gap in gaps]


def _messages(report: Dict[str, Any]) -> List[str]:
    messages: List[str] = []
    for key in ("errors", "warnings", "llm_errors", "llm_warnings"):
        raw = report.get(key, [])
        if isinstance(raw, list):
            messages.extend(str(item) for item in raw if str(item).strip())
    return messages


def _gap_type(message: str) -> str:
    text = message.lower()
    if "no primary evidence source" in text or "primary-source support" in text:
        return "missing_primary_evidence"
    if "missing evidence ids" in text or "not cited in markdown" in text or "missing evidence citations" in text:
        return "missing_evidence"
    if "multimodal consistency" in text or "chart" in text:
        return "multimodal_conflict"
    if "valuation reproducibility" in text or "valuation" in text or "dcf" in text:
        return "valuation_formula_error"
    if "target symbol mismatch" in text or "period" in text:
        return "entity_or_period_mismatch"
    return "unknown"


def _claim_id(message: str) -> str:
    match = re.search(r"\bClaim\s+([A-Za-z0-9_-]+)", message)
    return match.group(1) if match else ""


def _required_sources(gap_type: str) -> List[str]:
    if gap_type == "missing_primary_evidence":
        return ["10-K", "10-Q", "earnings_release", "company_ir", "exchange_filing"]
    if gap_type == "missing_evidence":
        return ["linked_evidence_record"]
    if gap_type == "multimodal_conflict":
        return ["tables.json", "charts.json", "claims.json"]
    if gap_type == "valuation_formula_error":
        return ["valuation_model.json", "valuation_assumptions.json", "valuation_sensitivity.json"]
    return []


def _required_fields(gap_type: str, message: str) -> List[str]:
    if gap_type == "missing_primary_evidence":
        return ["source_url", "authority_level", "source_document_type"]
    if gap_type == "missing_evidence":
        return ["evidence_id", "citation"]
    if gap_type == "multimodal_conflict":
        return ["input_table_ids", "input_claim_ids", "source_evidence_ids", "source_fields"]
    if gap_type == "valuation_formula_error":
        return ["denominator_value", "multiple", "enterprise_value_billion", "equity_value_billion"]
    return [message[:80]]


def _suggested_queries(claim: Dict[str, Any], symbol: str, period: str, gap_type: str) -> List[str]:
    text = str(claim.get("claim_text", "") if isinstance(claim, dict) else "").strip()
    base = " ".join(part for part in [symbol, period, text[:90]] if part).strip()
    if not base:
        base = " ".join(part for part in [symbol, period] if part).strip()
    if gap_type == "missing_primary_evidence":
        return [f"{base} earnings release", f"{base} 10-Q 10-K filing"]
    if gap_type == "missing_evidence":
        return [base]
    return []


def _claim_by_id(claims: List[Dict[str, Any]], claim_id: str) -> Dict[str, Any]:
    for claim in claims:
        if isinstance(claim, dict) and str(claim.get("claim_id", "")) == claim_id:
            return claim
    return {}
