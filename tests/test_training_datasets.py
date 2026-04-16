from pathlib import Path

from src.training.build_reranker_dataset import build_reranker_dataset
from src.training.build_rewriter_dataset import build_rewriter_dataset
from src.training.build_verifier_dataset import build_verifier_dataset


def test_build_reranker_dataset(tmp_path: Path):
    out_dir = tmp_path / "reranker"
    info = build_reranker_dataset(
        retrieval_path="data/outputs/retrieval_results.json",
        output_dir=out_dir,
    )
    assert Path(info["parquet"]).exists()
    assert Path(info["jsonl"]).exists()
    assert int(info["rows"]) >= 1


def test_build_rewriter_dataset(tmp_path: Path):
    out_dir = tmp_path / "rewriter"
    info = build_rewriter_dataset(
        claim_path="data/outputs/claim_table.json",
        output_dir=out_dir,
    )
    assert Path(info["parquet"]).exists()
    assert Path(info["jsonl"]).exists()
    assert int(info["rows"]) >= 1


def test_build_verifier_dataset(tmp_path: Path):
    out_dir = tmp_path / "verifier"
    info = build_verifier_dataset(
        claim_path="data/outputs/claim_table.json",
        verification_path="data/outputs/verification_report.json",
        output_dir=out_dir,
    )
    assert Path(info["parquet"]).exists()
    assert Path(info["jsonl"]).exists()
    assert int(info["rows"]) >= 1

