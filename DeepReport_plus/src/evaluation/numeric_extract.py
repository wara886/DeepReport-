"""Extract numeric claims for numeric_audit_v1."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List


_PCT_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*%")
_NUM_RE = re.compile(r"(-?\d+(?:\.\d+)?)")


@dataclass
class NumericClaim:
    case_id: str
    claim_id: str
    metric: str
    value: float
    unit: str
    period: str
    evidence_ids: List[str]

    def to_dict(self) -> Dict[str, object]:
        return {
            "case_id": self.case_id,
            "claim_id": self.claim_id,
            "metric": self.metric,
            "value": self.value,
            "unit": self.unit,
            "period": self.period,
            "evidence_ids": list(self.evidence_ids),
        }


def _safe_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_from_text(text: str, metric: str) -> float | None:
    lower = text.lower()
    if metric in {"yoy", "gross_margin"}:
        match = _PCT_RE.search(lower)
        return float(match.group(1)) if match else None
    match = _NUM_RE.search(lower)
    return float(match.group(1)) if match else None


def extract_numeric_claims(
    case_id: str,
    period: str,
    claims: Iterable[Dict[str, object]],
) -> List[NumericClaim]:
    """Extract canonical numeric claims from claim table rows."""

    output: List[NumericClaim] = []
    for item in claims:
        claim_id = str(item.get("claim_id", "")).strip()
        text = str(item.get("claim_text", ""))
        evidence_ids = [str(x) for x in list(item.get("evidence_ids", []))]
        numeric_values = item.get("numeric_values") or {}
        if not isinstance(numeric_values, dict):
            numeric_values = {}

        revenue = _safe_float(numeric_values.get("revenue_billion", numeric_values.get("revenue")))
        if revenue is None and "revenue" in text.lower():
            revenue = _extract_from_text(text, "revenue")
        if revenue is not None:
            output.append(
                NumericClaim(
                    case_id=case_id,
                    claim_id=claim_id,
                    metric="revenue",
                    value=revenue,
                    unit="billion",
                    period=period,
                    evidence_ids=evidence_ids,
                )
            )

        gross_margin = _safe_float(numeric_values.get("gross_margin_pct", numeric_values.get("gross_margin")))
        if gross_margin is None and "gross margin" in text.lower():
            gross_margin = _extract_from_text(text, "gross_margin")
        if gross_margin is not None:
            output.append(
                NumericClaim(
                    case_id=case_id,
                    claim_id=claim_id,
                    metric="gross_margin",
                    value=gross_margin,
                    unit="pct",
                    period=period,
                    evidence_ids=evidence_ids,
                )
            )

        yoy = _safe_float(
            numeric_values.get("yoy", numeric_values.get("yoy_pct", numeric_values.get("revenue_growth_pct")))
        )
        if yoy is None and ("同比" in text or "growth" in text.lower() or "yoy" in text.lower()):
            yoy = _extract_from_text(text, "yoy")
        if yoy is not None:
            output.append(
                NumericClaim(
                    case_id=case_id,
                    claim_id=claim_id,
                    metric="yoy",
                    value=yoy,
                    unit="pct",
                    period=period,
                    evidence_ids=evidence_ids,
                )
            )

        net_income = _safe_float(numeric_values.get("net_income_billion", numeric_values.get("net_income")))
        if net_income is None:
            revenue_for_ni = _safe_float(numeric_values.get("revenue_billion"))
            net_margin_pct = _safe_float(numeric_values.get("net_margin_pct"))
            if revenue_for_ni is not None and net_margin_pct is not None:
                net_income = revenue_for_ni * net_margin_pct / 100.0
        if net_income is None and ("net income" in text.lower() or "净利润" in text):
            net_income = _extract_from_text(text, "net_income")
        if net_income is not None:
            output.append(
                NumericClaim(
                    case_id=case_id,
                    claim_id=claim_id,
                    metric="net_income",
                    value=net_income,
                    unit="billion",
                    period=period,
                    evidence_ids=evidence_ids,
                )
            )
    return output


def extract_gold_numeric_facts(case: Dict[str, object]) -> List[Dict[str, object]]:
    """Normalize gold_numeric_facts from eval case payload."""

    output: List[Dict[str, object]] = []
    for item in list(case.get("gold_numeric_facts", [])):
        if not isinstance(item, dict):
            continue
        metric = str(item.get("metric", "")).strip()
        value = _safe_float(item.get("value"))
        unit = str(item.get("unit", "")).strip() or "unknown"
        period = str(item.get("period", "")).strip()
        output.append(
            {
                "metric": metric,
                "value": value,
                "unit": unit,
                "period": period,
            }
        )
    return output

