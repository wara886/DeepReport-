"""Verifier inference with checkpoint fallback."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List


def _load_checkpoint(path: str | Path) -> Dict[str, object] | None:
    p = Path(path)
    if not p.exists():
        return None
    return dict(json.loads(p.read_text(encoding="utf-8")))


def verify_claims(
    claims: List[Dict[str, object]],
    checkpoint_path: str = "data/outputs/checkpoints/verifier_checkpoint.json",
) -> Dict[str, object]:
    ckpt = _load_checkpoint(checkpoint_path)
    threshold = float(ckpt.get("confidence_threshold", 0.5)) if ckpt else 0.5

    passed_ids: List[str] = []
    failed_ids: List[str] = []
    for item in claims:
        cid = str(item.get("claim_id", ""))
        conf = float(item.get("confidence", 0.0))
        if conf >= threshold:
            passed_ids.append(cid)
        else:
            failed_ids.append(cid)

    return {
        "checkpoint_used": bool(ckpt),
        "threshold": threshold,
        "passed_count": len(passed_ids),
        "failed_count": len(failed_ids),
        "passed_claim_ids": passed_ids,
        "failed_claim_ids": failed_ids,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run verifier inference with fallback.")
    parser.add_argument("--claim-path", default="data/outputs/claim_table.json")
    parser.add_argument("--checkpoint-path", default="data/outputs/checkpoints/verifier_checkpoint.json")
    parser.add_argument("--output-path", default="data/outputs/verification_infer_report.json")
    args = parser.parse_args()

    claims = list(json.loads(Path(args.claim_path).read_text(encoding="utf-8")))
    report = verify_claims(claims, checkpoint_path=args.checkpoint_path)
    out = Path(args.output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[stage9] verifier infer report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

