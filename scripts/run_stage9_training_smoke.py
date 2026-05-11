#!/usr/bin/env python3
"""Stage 9 smoke runner."""

from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.generation.rewriter_infer import rewrite_claims
from src.training.infer_reranker import rerank_hits
from src.training.infer_verifier import verify_claims
from src.training.train_reranker import train_reranker
from src.training.train_rewriter import train_rewriter
from src.training.train_verifier import train_verifier
import json


def main() -> int:
    ckpt_r = train_reranker()
    ckpt_w = train_rewriter()
    ckpt_v = train_verifier()
    print(f"[stage9] trained: {ckpt_r}")
    print(f"[stage9] trained: {ckpt_w}")
    print(f"[stage9] trained: {ckpt_v}")

    retrieval = json.loads(Path("data/outputs/retrieval_results.json").read_text(encoding="utf-8"))
    hits = rerank_hits(list(retrieval.get("hits", [])))
    Path("data/outputs/reranked_results.json").write_text(
        json.dumps({"query": retrieval.get("query", ""), "hits": hits}, indent=2),
        encoding="utf-8",
    )
    print("[stage9] infer reranker -> data/outputs/reranked_results.json")

    claims = list(json.loads(Path("data/outputs/claim_table.json").read_text(encoding="utf-8")))
    verify_report = verify_claims(claims)
    Path("data/outputs/verification_infer_report.json").write_text(
        json.dumps(verify_report, indent=2), encoding="utf-8"
    )
    print("[stage9] infer verifier -> data/outputs/verification_infer_report.json")

    rewritten = rewrite_claims(claims)
    Path("data/outputs/rewriter_infer_results.json").write_text(
        json.dumps(rewritten, indent=2), encoding="utf-8"
    )
    print("[stage9] infer rewriter -> data/outputs/rewriter_infer_results.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

