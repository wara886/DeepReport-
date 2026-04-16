"""Build verifier training dataset from claims and verification report."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import pandas as pd


def _load_json(path: str | Path) -> object:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"file not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def build_verifier_dataset(
    claim_path: str | Path = "data/outputs/claim_table.json",
    verification_path: str | Path = "data/outputs/verification_report.json",
    output_dir: str | Path = "data/outputs/training/verifier",
) -> Dict[str, str]:
    claims = list(_load_json(claim_path))
    verification = dict(_load_json(verification_path))

    global_passed = bool(verification.get("passed", False))
    rows: List[Dict[str, object]] = []

    for claim in claims:
        confidence = float(claim.get("confidence", 0.0))
        label = 1 if global_passed and confidence >= 0.5 else 0
        rows.append(
            {
                "claim_id": claim.get("claim_id", ""),
                "section_name": claim.get("section_name", ""),
                "claim_text": claim.get("claim_text", ""),
                "confidence": confidence,
                "risk_level": claim.get("risk_level", "unknown"),
                "label": label,
            }
        )

    if not rows:
        rows.append(
            {
                "claim_id": "cl_empty",
                "section_name": "unknown",
                "claim_text": "",
                "confidence": 0.0,
                "risk_level": "unknown",
                "label": 0,
            }
        )

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame(rows)
    parquet_path = out_dir / "dataset.parquet"
    jsonl_path = out_dir / "dataset.jsonl"
    df.to_parquet(parquet_path, index=False)
    with jsonl_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    return {
        "parquet": str(parquet_path),
        "jsonl": str(jsonl_path),
        "rows": str(len(rows)),
    }

