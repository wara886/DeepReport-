"""Build section-scoped evidence packs for report verification and repair."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


SECTION_KEY_ALIASES = {
    "investment_conclusion": "conclusion",
    "risk": "risks",
    "risk_factors": "risks",
}


def build_section_evidence_packs(output_dir: str | Path) -> dict[str, Any]:
    outputs = Path(output_dir)
    contracts = _mapping(_read_json(outputs / "report_section_contracts.json", {}), "contracts")
    dossiers = _read_json(outputs / "section_dossiers.json", {})
    dossiers = dossiers if isinstance(dossiers, dict) else {}
    evidence = _records(_read_json(outputs / "evidence.json", []), ("evidence", "items", "records"))
    claims = _records(_read_json(outputs / "claims.json", []), ("claims", "items", "records"))
    canonical = _read_json(outputs / "canonical_metrics.json", {})
    citations = _records(_read_json(outputs / "citations.json", []), ("citations", "items", "records"))
    citation_map = _records(
        _read_json(outputs / "citation_map.json", []),
        ("citation_map", "citations", "items", "records"),
    )
    citation_labels: dict[str, list[str]] = {}
    for row in citations + citation_map:
        evidence_id = str(row.get("evidence_id") or "")
        label = row.get("citation_number")
        if evidence_id and label not in (None, ""):
            citation_labels[evidence_id] = _dedupe(citation_labels.get(evidence_id, []) + [str(label)])
    prior_verification = _read_json(outputs / "section_verification.json", {})
    evidence_by_id = {_evidence_id(row): row for row in evidence if _evidence_id(row)}
    unsupported_claim_ids = _unsupported_claim_ids(_read_json(outputs / "verification_report.json", {}))

    packs: dict[str, Any] = {}
    raw_keys = set(contracts) | set(dossiers)
    section_keys = sorted({_canonical_section_key(key) for key in raw_keys})
    for section_key in section_keys:
        aliases = [key for key in raw_keys if _canonical_section_key(key) == section_key]
        contract = _merge_section_payloads(contracts, aliases, preferred_key=section_key)
        dossier = _merge_section_payloads(dossiers, aliases, preferred_key=section_key)
        section_claims = _section_claims(section_key, claims, dossier)
        contract_ids = _dedupe(_strings(contract.get("citation_evidence_ids")))
        claim_ids = _dedupe(
            evidence_id
            for claim in section_claims
            for evidence_id in _strings(claim.get("evidence_ids"))
        )
        dossier_ids = _dedupe(_strings(dossier.get("supporting_evidence_ids")))
        # A must-use list is a small writing contract, not the complete retrieval
        # result. Prefer explicit contract evidence; otherwise use claim-linked
        # evidence as a bounded fallback.
        required_ids = contract_ids[:5] if contract_ids else claim_ids[:3]
        must_use = [_evidence_summary(evidence_by_id[item], citation_labels.get(item, [])) for item in required_ids if item in evidence_by_id]
        missing = [item for item in required_ids if item not in evidence_by_id]
        supporting_ids = _dedupe(required_ids + claim_ids + dossier_ids)
        supporting = [_evidence_summary(evidence_by_id[item], citation_labels.get(item, [])) for item in supporting_ids if item in evidence_by_id]
        conflicts = [row for row in supporting if _evidence_conflicted(row)]
        claim_rows = []
        for claim in section_claims:
            claim_id = str(claim.get("claim_id") or "")
            claim_evidence = _strings(claim.get("evidence_ids"))
            available = [item for item in claim_evidence if item in evidence_by_id]
            supported = bool(available) and claim_id not in unsupported_claim_ids
            claim_rows.append({
                "claim_id": claim_id,
                "claim_text": str(claim.get("claim_text") or ""),
                "evidence_ids": claim_evidence,
                "available_evidence_ids": available,
                "verification_status": "supported" if supported else "unsupported",
            })
        prior = _mapping(prior_verification, "section_results").get(section_key)
        prior = prior if isinstance(prior, dict) else {}
        packs[section_key] = {
            "section_key": section_key,
            "title": str(contract.get("title") or dossier.get("section_title") or section_key),
            "contract_status": str(contract.get("status") or "unknown"),
            "failed_contract_reasons": _dedupe(
                _strings(contract.get("blocked_reasons")) + _strings(prior.get("reasons"))
            ),
            "must_use_evidence": must_use,
            "must_use_evidence_ids": [row["evidence_id"] for row in must_use],
            "supporting_evidence": supporting,
            "conflicting_evidence": conflicts,
            "missing_evidence_ids": missing,
            "canonical_metrics": _canonical_for_section(section_key, canonical),
            "claims": claim_rows,
            "unsupported_claim_ids": [row["claim_id"] for row in claim_rows if row["verification_status"] != "supported"],
        }

    artifact = {
        "schema_version": "section_evidence_packs.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "ready" if packs else "missing",
        "section_count": len(packs),
        "packs": packs,
    }
    outputs.mkdir(parents=True, exist_ok=True)
    (outputs / "section_evidence_packs.json").write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return artifact


def _section_claims(section_key: str, claims: list[dict[str, Any]], dossier: dict[str, Any]) -> list[dict[str, Any]]:
    aliases = {
        "executive_summary": {"executive_summary", "summary"},
        "business_overview": {"business_overview", "business_profile", "strategy_business"},
        "financial_analysis": {"financial_analysis", "financial_statements", "earnings_quality"},
        "valuation": {"valuation", "peer_compare", "valuation_sensitivity"},
        "risks": {"risks", "risk", "risk_factors"},
        "conclusion": {"conclusion", "investment_conclusion"},
    }.get(section_key, {section_key})
    selected = [row for row in claims if str(row.get("section_name") or row.get("section_key") or "") in aliases]
    known = {str(row.get("claim_id") or "") for row in selected}
    by_id = {str(row.get("claim_id") or ""): row for row in claims}
    for item in dossier.get("supported_claims") or []:
        if not isinstance(item, dict):
            continue
        claim_id = str(item.get("claim_id") or "")
        if claim_id and claim_id not in known:
            selected.append(dict(by_id.get(claim_id) or item))
            known.add(claim_id)
    return selected


def _canonical_section_key(section_key: Any) -> str:
    key = str(section_key or "")
    return SECTION_KEY_ALIASES.get(key, key)


def _merge_section_payloads(
    source: dict[str, Any],
    keys: list[str],
    *,
    preferred_key: str,
) -> dict[str, Any]:
    ordered = [key for key in keys if key != preferred_key]
    if preferred_key in keys:
        ordered.append(preferred_key)
    merged: dict[str, Any] = {}
    list_keys = {
        "citation_evidence_ids",
        "supporting_evidence_ids",
        "blocked_reasons",
        "supported_claims",
    }
    for key in ordered:
        payload = source.get(key)
        if not isinstance(payload, dict):
            continue
        for field, value in payload.items():
            if field in list_keys and isinstance(value, list):
                merged[field] = _dedupe_values(list(merged.get(field) or []) + value)
            elif value not in (None, "", [], {}):
                merged[field] = value
    return merged


def _dedupe_values(values: list[Any]) -> list[Any]:
    output: list[Any] = []
    seen: set[str] = set()
    for value in values:
        identity = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        if identity in seen:
            continue
        seen.add(identity)
        output.append(value)
    return output


def _evidence_summary(row: dict[str, Any], citation_labels: list[str] | None = None) -> dict[str, Any]:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    period = str(row.get("period") or row.get("data_cutoff") or metadata.get("period") or metadata.get("data_cutoff") or "")
    authority = str(row.get("source_authority") or row.get("authority_level") or metadata.get("source_authority") or row.get("trust_level") or "unknown")
    return {
        "evidence_id": _evidence_id(row),
        "identity_key": str(row.get("identity_key") or metadata.get("identity_key") or ""),
        "title": str(row.get("title") or ""),
        "source_type": str(row.get("source_type") or ""),
        "source_url": str(row.get("source_url") or ""),
        "period": period,
        "authority": authority,
        "authority_score": row.get("authority_score", metadata.get("authority_score")),
        "citation_labels": list(citation_labels or []),
        "content_excerpt": str(row.get("content") or "")[:800],
    }


def _canonical_for_section(section_key: str, payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    rows = payload.get("metrics") if isinstance(payload.get("metrics"), list) else []
    if not rows and isinstance(payload.get("canonical_metrics"), dict):
        rows = [dict(value, metric_name=key) for key, value in payload["canonical_metrics"].items() if isinstance(value, dict)]
    if section_key not in {"executive_summary", "financial_analysis", "valuation", "conclusion"}:
        return []
    return [dict(row) for row in rows if isinstance(row, dict)]


def _unsupported_claim_ids(payload: Any) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    output: set[str] = set()
    for key in ("errors", "evidence_gaps", "warnings"):
        for item in payload.get(key) or []:
            if not isinstance(item, dict):
                continue
            claim_id = str(item.get("claim_id") or "")
            text = " ".join(str(item.get(name) or "") for name in ("reason", "message", "type", "category")).lower()
            if claim_id and any(token in text for token in ("unsupported", "missing evidence", "evidence gap", "unverified")):
                output.add(claim_id)
    return output


def _evidence_conflicted(row: dict[str, Any]) -> bool:
    text = " ".join(str(row.get(key) or "") for key in ("period", "authority", "source_type")).lower()
    return "mismatch" in text or "conflict" in text


def _evidence_id(row: dict[str, Any]) -> str:
    return str(row.get("evidence_id") or row.get("sample_id") or row.get("identity_key") or "")


def _mapping(payload: Any, key: str) -> dict[str, Any]:
    value = payload.get(key) if isinstance(payload, dict) else None
    return value if isinstance(value, dict) else {}


def _records(payload: Any, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if isinstance(value, list):
                return [dict(row) for row in value if isinstance(row, dict)]
    return []


def _strings(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return [str(value)] if value not in (None, "") else []


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except (OSError, json.JSONDecodeError):
        return default
