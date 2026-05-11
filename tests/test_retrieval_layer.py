from pathlib import Path

import pandas as pd

from src.retrieval.bm25_index import BM25Index
from src.retrieval.evidence_store import EvidenceRecord, EvidenceStore
from src.retrieval.retrieve import retrieve_evidence, retrieve_evidence_with_mode


def _write_curated_inputs(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        [
            {
                "sample_id": "s1",
                "source_type": "financials",
                "symbol": "AAPL",
                "period": "2025Q4",
                "title": "AAPL 10-Q summary",
                "publish_time": "2026-01-30T00:00:00Z",
                "content": "Revenue 126.3B and gross margin 46.8%.",
                "source_url": "https://example.com/aapl",
                "trust_level": "high",
            },
            {
                "sample_id": "s2",
                "source_type": "news",
                "symbol": "MSFT",
                "period": "2025Q4",
                "title": "MSFT market update",
                "publish_time": "2026-02-01T00:00:00Z",
                "content": "Risk remains moderate while enterprise demand is stable.",
                "source_url": "https://example.com/msft",
                "trust_level": "medium",
            },
        ]
    )
    frame.to_parquet(root / "sample.parquet", index=False)


def test_bm25_index_ranks_relevant_doc():
    records = [
        EvidenceRecord.from_dict(
            {
                "sample_id": "s1",
                "source_type": "news",
                "symbol": "AAPL",
                "period": "2025Q4",
                "title": "Revenue jumps",
                "publish_time": "2026-01-01",
                "content": "Revenue increased and margin improved",
                "source_url": "https://example.com/1",
                "trust_level": "high",
            }
        ),
        EvidenceRecord.from_dict(
            {
                "sample_id": "s2",
                "source_type": "news",
                "symbol": "MSFT",
                "period": "2025Q4",
                "title": "General update",
                "publish_time": "2026-01-02",
                "content": "No strong financial details",
                "source_url": "https://example.com/2",
                "trust_level": "medium",
            }
        ),
    ]
    index = BM25Index(records)
    hits = index.search("revenue margin", topk=1)
    assert len(hits) == 1
    assert hits[0].record.sample_id == "s1"


def test_retrieve_evidence_from_curated_dir(tmp_path: Path):
    curated = tmp_path / "curated"
    _write_curated_inputs(curated)
    hits = retrieve_evidence(query="gross margin revenue", topk=3, curated_dir=str(curated))
    assert len(hits) >= 1
    assert hits[0]["symbol"] == "AAPL"
    assert "score" in hits[0]


def test_evidence_store_filter(tmp_path: Path):
    curated = tmp_path / "curated"
    _write_curated_inputs(curated)
    store = EvidenceStore.from_curated_parquet(curated_dir=curated)
    aapl_only = store.filter(symbol="AAPL")
    assert len(aapl_only) == 1
    assert aapl_only[0].symbol == "AAPL"


def test_retrieve_evidence_vector_mode_from_curated_dir(tmp_path: Path):
    curated = tmp_path / "curated"
    _write_curated_inputs(curated)

    hits, meta = retrieve_evidence_with_mode(
        query="gross margin revenue",
        topk=3,
        curated_dir=str(curated),
        ranking_mode="vector",
        log=False,
    )

    assert hits
    assert hits[0]["symbol"] == "AAPL"
    assert meta["mode"] == "vector"
    assert meta["vector_backend"] in {"memory", "chromadb"}


def test_retrieve_evidence_hybrid_rerank_mode_from_curated_dir(tmp_path: Path):
    curated = tmp_path / "curated"
    _write_curated_inputs(curated)
    checkpoint = tmp_path / "reranker_checkpoint.json"
    checkpoint.write_text('{"trained": true, "model_name": "BAAI/bge-reranker-base"}', encoding="utf-8")

    hits, meta = retrieve_evidence_with_mode(
        query="gross margin revenue",
        topk=3,
        curated_dir=str(curated),
        ranking_mode="hybrid_rerank",
        reranker_checkpoint_path=str(checkpoint),
        log=False,
    )

    assert hits
    assert hits[0]["symbol"] == "AAPL"
    assert meta["mode"] == "hybrid_rerank"
    assert meta["checkpoint_used"] is True
    assert meta["source_record_count"] == 2
    assert meta["record_count"] == 2
    assert meta["returned_hit_count"] >= 1
    assert meta["failure_reason"] == ""


def test_retrieve_evidence_reports_failure_reason_for_missing_symbol(tmp_path: Path):
    curated = tmp_path / "curated"
    _write_curated_inputs(curated)

    hits, meta = retrieve_evidence_with_mode(
        query="revenue",
        topk=3,
        curated_dir=str(curated),
        symbol="NVDA",
        period="2025Q4",
        ranking_mode="bm25",
        log=False,
    )

    assert hits == []
    assert meta["failure_reason"] == "no_records_for_symbol_period"
