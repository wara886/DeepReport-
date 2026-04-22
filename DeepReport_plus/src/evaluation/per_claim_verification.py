"""Per-claim verification diagnostics export."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, List


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_float(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _load_threshold(checkpoint_path: Path) -> float:
    if not checkpoint_path.exists():
        return 0.5
    payload = dict(_read_json(checkpoint_path))
    return _safe_float(payload.get("confidence_threshold", 0.5), 0.5)


def _review_priority(
    is_grounded: bool,
    confidence: float,
    threshold: float,
    evidence_ids: List[str],
    numeric_values: Dict[str, object],
) -> str:
    if not is_grounded:
        return "high"
    if abs(confidence - threshold) <= 0.03:
        return "medium"
    if not evidence_ids or not numeric_values:
        return "medium"
    return "low"


def _build_notes(
    is_grounded: bool,
    confidence: float,
    threshold: float,
    evidence_ids: List[str],
    numeric_values: Dict[str, object],
) -> str:
    reasons: List[str] = [f"is_grounded = confidence({confidence:.4f}) >= threshold({threshold:.4f})"]
    if not is_grounded:
        reasons.append("confidence_below_threshold")
    if abs(confidence - threshold) <= 0.03:
        reasons.append("near_threshold_boundary")
    if not evidence_ids:
        reasons.append("missing_evidence_ids")
    if not numeric_values:
        reasons.append("missing_numeric_values")
    return "; ".join(reasons)


def export_per_claim_verification(
    claim_path: str | Path,
    output_dir: str | Path | None = None,
    checkpoint_path: str | Path = "data/outputs/checkpoints/verifier_checkpoint.json",
    json_name: str = "per_claim_verification.json",
    csv_name: str = "per_claim_verification.csv",
) -> Dict[str, object]:
    claim_file = Path(claim_path)
    if not claim_file.exists():
        raise FileNotFoundError(f"claim_table.json not found: {claim_file}")

    out_dir = Path(output_dir) if output_dir else claim_file.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    threshold = _load_threshold(Path(checkpoint_path))
    claims = list(_read_json(claim_file))

    rows: List[Dict[str, object]] = []
    for raw in claims:
        item = dict(raw)
        confidence = _safe_float(item.get("confidence", 0.0), 0.0)
        evidence_ids = [str(x) for x in list(item.get("evidence_ids", []))]
        numeric_values = dict(item.get("numeric_values", {}))
        is_grounded = confidence >= threshold
        review_priority = _review_priority(
            is_grounded=is_grounded,
            confidence=confidence,
            threshold=threshold,
            evidence_ids=evidence_ids,
            numeric_values=numeric_values,
        )
        notes = _build_notes(
            is_grounded=is_grounded,
            confidence=confidence,
            threshold=threshold,
            evidence_ids=evidence_ids,
            numeric_values=numeric_values,
        )
        rows.append(
            {
                "claim_id": str(item.get("claim_id", "")),
                "claim_text": str(item.get("claim_text", "")),
                "section_name": str(item.get("section_name", "")),
                "confidence": confidence,
                "threshold": threshold,
                "is_grounded": is_grounded,
                "evidence_ids": evidence_ids,
                "numeric_values": numeric_values,
                "review_priority": review_priority,
                "notes": notes,
            }
        )

    json_path = out_dir / json_name
    csv_path = out_dir / csv_name
    json_payload = {
        "threshold": threshold,
        "rule": "is_grounded = confidence >= threshold",
        "claim_count": len(rows),
        "grounded_count": sum(1 for row in rows if bool(row["is_grounded"])),
        "rows": rows,
    }
    json_path.write_text(json.dumps(json_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    fieldnames = [
        "claim_id",
        "claim_text",
        "section_name",
        "confidence",
        "threshold",
        "is_grounded",
        "evidence_ids",
        "numeric_values",
        "review_priority",
        "notes",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            csv_row = dict(row)
            csv_row["evidence_ids"] = json.dumps(row["evidence_ids"], ensure_ascii=False)
            csv_row["numeric_values"] = json.dumps(row["numeric_values"], ensure_ascii=False)
            writer.writerow(csv_row)

    return {
        "per_claim_verification_json": str(json_path),
        "per_claim_verification_csv": str(csv_path),
        "threshold": threshold,
        "claim_count": len(rows),
    }
