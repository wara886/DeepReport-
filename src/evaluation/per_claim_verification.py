"""Claim-level verification export for the core report pipeline."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, Iterable, List


def _load_checkpoint(path: str | Path) -> Dict[str, object] | None:
    checkpoint_path = Path(path)
    if not checkpoint_path.exists():
        return None
    return dict(json.loads(checkpoint_path.read_text(encoding="utf-8")))


def _verify_claims(claims: Iterable[Dict[str, object]], checkpoint_path: str | Path) -> Dict[str, object]:
    checkpoint = _load_checkpoint(checkpoint_path)
    threshold = float(checkpoint.get("confidence_threshold", 0.5)) if checkpoint else 0.5
    checkpoint_used = bool(checkpoint)

    rows: List[Dict[str, object]] = []
    for claim in claims:
        confidence = float(claim.get("confidence", 0.0))
        evidence_ids = list(claim.get("evidence_ids", []))
        is_grounded = confidence >= threshold
        rows.append(
            {
                "claim_id": str(claim.get("claim_id", "")),
                "section_name": str(claim.get("section_name", "")),
                "confidence": confidence,
                "evidence_count": len(evidence_ids),
                "is_grounded": is_grounded,
                "threshold": threshold,
                "checkpoint_used": checkpoint_used,
                "review_priority": "low" if is_grounded else "high",
                "notes": (
                    f"is_grounded = confidence({confidence:.4f}) >= threshold({threshold:.4f})"
                ),
            }
        )
    grounded_count = sum(1 for row in rows if bool(row["is_grounded"]))
    return {
        "threshold": threshold,
        "rule": "is_grounded = confidence >= threshold",
        "claim_count": len(rows),
        "grounded_count": grounded_count,
        "checkpoint_used": checkpoint_used,
        "rows": rows,
    }


def export_per_claim_verification(
    claim_path: str | Path,
    output_dir: str | Path,
    checkpoint_path: str | Path = "data/outputs/checkpoints/verifier_checkpoint.json",
    use_candidate_grounded_rule: bool = False,
) -> Dict[str, str]:
    """Export JSON/CSV verification rows for every claim.

    `use_candidate_grounded_rule` is accepted for backwards-compatible callers, but
    experimental grounded-rule shadow logic is intentionally outside the cleaned
    core repository.
    """

    del use_candidate_grounded_rule
    claims = list(json.loads(Path(claim_path).read_text(encoding="utf-8")))
    payload = _verify_claims(claims, checkpoint_path=checkpoint_path)
    rows = list(payload["rows"])

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "per_claim_verification.json"
    csv_path = out_dir / "per_claim_verification.csv"

    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        fieldnames = [
            "claim_id",
            "section_name",
            "confidence",
            "evidence_count",
            "is_grounded",
            "threshold",
            "checkpoint_used",
            "review_priority",
            "notes",
        ]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return {
        "per_claim_verification_json": str(json_path),
        "per_claim_verification_csv": str(csv_path),
    }
