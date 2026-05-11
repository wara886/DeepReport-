import json
from pathlib import Path

import pandas as pd

from src.training.build_reranker_dataset import build_reranker_dataset
from src.training.build_rewriter_dataset import build_rewriter_dataset
from src.training.build_verifier_dataset import build_verifier_dataset


def test_build_reranker_dataset(tmp_path: Path):
    out_dir = tmp_path / "reranker"
    retrieval_path = tmp_path / "retrieval_results.json"
    retrieval_path.write_text(
        json.dumps(
            {
                "query": "revenue margin",
                "hits": [
                    {
                        "sample_id": "ev_1",
                        "title": "AAPL financial snapshot",
                        "content": "Revenue 100B and gross margin 40%.",
                        "source_type": "financials",
                        "source_url": "https://example.com/financials",
                        "trust_level": "high",
                        "score": 1.0,
                    },
                    {
                        "sample_id": "ev_2",
                        "title": "AAPL commentary",
                        "content": "Revenue discussion with less precise support.",
                        "source_type": "news",
                        "source_url": "https://example.com/news",
                        "trust_level": "medium",
                        "score": 0.8,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    info = build_reranker_dataset(
        retrieval_path=retrieval_path,
        output_dir=out_dir,
    )
    assert Path(info["parquet"]).exists()
    assert Path(info["jsonl"]).exists()
    assert int(info["rows"]) >= 1
    df = pd.read_parquet(info["parquet"])
    assert {"query", "doc_id", "doc_text", "source_type", "source_url", "trust_level", "hard_negative", "label"}.issubset(df.columns)
    assert int(df["label"].sum()) == 1
    assert bool(df[df["doc_id"] == "ev_2"]["hard_negative"].iloc[0]) is True


def test_build_rewriter_dataset(tmp_path: Path):
    out_dir = tmp_path / "rewriter"
    claim_path = tmp_path / "claim_table.json"
    claim_path.write_text(
        json.dumps(
            [
                {
                    "claim_id": "cl_1",
                    "section_name": "financial_analysis",
                    "claim_text": "AAPL revenue is near 100B.",
                    "confidence": 0.8,
                    "evidence_ids": ["ev_1"],
                }
            ]
        ),
        encoding="utf-8",
    )
    info = build_rewriter_dataset(
        claim_path=claim_path,
        output_dir=out_dir,
    )
    assert Path(info["parquet"]).exists()
    assert Path(info["jsonl"]).exists()
    assert int(info["rows"]) >= 1


def test_build_verifier_dataset(tmp_path: Path):
    out_dir = tmp_path / "verifier"
    claim_path = tmp_path / "claim_table.json"
    verification_path = tmp_path / "verification_report.json"
    claim_path.write_text(
        json.dumps(
            [
                {
                    "claim_id": "cl_1",
                    "section_name": "financial_analysis",
                    "claim_text": "AAPL revenue is near 100B.",
                    "confidence": 0.8,
                    "risk_level": "low",
                }
            ]
        ),
        encoding="utf-8",
    )
    verification_path.write_text(json.dumps({"passed": True}), encoding="utf-8")
    info = build_verifier_dataset(
        claim_path=claim_path,
        verification_path=verification_path,
        output_dir=out_dir,
    )
    assert Path(info["parquet"]).exists()
    assert Path(info["jsonl"]).exists()
    assert int(info["rows"]) >= 1
