from pathlib import Path

import pandas as pd

from src.retrieval.bm25_index import BM25Index
from src.retrieval.evidence_store import EvidenceRecord, EvidenceStore
from src.retrieval.retrieve import retrieve_evidence


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

