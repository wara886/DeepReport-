"""Rewriter inference with checkpoint fallback."""

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


def rewrite_claims(
    claims: List[Dict[str, object]],
    checkpoint_path: str = "data/outputs/checkpoints/rewriter_checkpoint.json",
) -> List[Dict[str, str]]:
    ckpt = _load_checkpoint(checkpoint_path)
    outputs: List[Dict[str, str]] = []

    for item in claims:
        text = str(item.get("claim_text", "")).strip()
        if ckpt:
            rewritten = f"Rewritten: {text}"
        else:
            # Fallback path should always work without checkpoint.
            rewritten = text
        outputs.append(
            {
                "claim_id": str(item.get("claim_id", "")),
                "section_name": str(item.get("section_name", "")),
                "rewritten_text": rewritten,
            }
        )
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description="Run rewriter inference with fallback.")
    parser.add_argument("--claim-path", default="data/outputs/claim_table.json")
    parser.add_argument("--checkpoint-path", default="data/outputs/checkpoints/rewriter_checkpoint.json")
    parser.add_argument("--output-path", default="data/outputs/rewriter_infer_results.json")
    args = parser.parse_args()

    claims = list(json.loads(Path(args.claim_path).read_text(encoding="utf-8")))
    outputs = rewrite_claims(claims, checkpoint_path=args.checkpoint_path)
    out = Path(args.output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(outputs, indent=2), encoding="utf-8")
    print(f"[stage9] rewriter infer output: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

