import json
from pathlib import Path

from src.generation.rewriter_infer import rewrite_claims
from src.training.infer_reranker import rerank_hits
from src.training.infer_verifier import verify_claims


def test_reranker_fallback_without_checkpoint():
    hits = [{"sample_id": "s1", "score": 1.2, "trust_level": "high"}]
    out = rerank_hits(hits, checkpoint_path="data/outputs/checkpoints/does_not_exist.json")
    assert len(out) == 1
    assert "rerank_score" in out[0]


def test_verifier_fallback_without_checkpoint():
    claims = [{"claim_id": "cl1", "confidence": 0.6}, {"claim_id": "cl2", "confidence": 0.4}]
    report = verify_claims(claims, checkpoint_path="data/outputs/checkpoints/does_not_exist.json")
    assert report["checkpoint_used"] is False
    assert report["threshold"] == 0.5


def test_rewriter_fallback_without_checkpoint():
    claims = [{"claim_id": "cl1", "section_name": "s", "claim_text": "alpha"}]
    rows = rewrite_claims(claims, checkpoint_path="data/outputs/checkpoints/does_not_exist.json")
    assert rows[0]["rewritten_text"] == "alpha"

