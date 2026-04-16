"""Build rewriter training dataset from claims and report outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import pandas as pd


def _load_claims(path: str | Path = "data/outputs/claim_table.json") -> List[Dict[str, object]]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"claim table not found: {p}")
    return list(json.loads(p.read_text(encoding="utf-8")))


def build_rewriter_dataset(
    claim_path: str | Path = "data/outputs/claim_table.json",
    output_dir: str | Path = "data/outputs/training/rewriter",
) -> Dict[str, str]:
    claims = _load_claims(claim_path)

    rows: List[Dict[str, object]] = []
    for claim in claims:
        claim_text = str(claim.get("claim_text", "")).strip()
        section_name = str(claim.get("section_name", "")).strip()
        prompt = f"Rewrite the claim into concise report sentence for section `{section_name}`."
        target = claim_text
        rows.append(
            {
                "claim_id": claim.get("claim_id", ""),
                "section_name": section_name,
                "prompt": prompt,
                "input_text": claim_text,
                "target_text": target,
            }
        )

    if not rows:
        rows.append(
            {
                "claim_id": "cl_empty",
                "section_name": "unknown",
                "prompt": "Rewrite empty claim.",
                "input_text": "",
                "target_text": "",
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

