from pathlib import Path

import pandas as pd

from src.retrieval.bm25_index import BM25Index
from src.retrieval.chroma_index import ChromaIndex
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
    assert store.load_meta["loaded_file_count"] == 1


def test_evidence_store_filters_runtime_identity_and_role():
    records = [
        EvidenceRecord.from_dict(
            {
                "evidence_id": "target_ev",
                "symbol": "MSFT",
                "period": "FY2024",
                "source_type": "sec_filing",
                "title": "MSFT filing",
                "content": "Microsoft filing",
                "provenance": {"task_id": "task-msft", "run_id": "run-msft"},
                "company_identity": {"company_id": 15},
                "metadata": {"evidence_role": "target"},
            }
        ),
        EvidenceRecord.from_dict(
            {
                "evidence_id": "peer_ev",
                "symbol": "NVDA",
                "period": "FY2024",
                "source_type": "market_data",
                "title": "NVDA peer snapshot",
                "content": "NVIDIA peer data",
                "provenance": {"task_id": "task-msft", "run_id": "run-msft"},
                "company_identity": {"company_id": 17},
                "metadata": {"evidence_role": "peer"},
            }
        ),
    ]
    store = EvidenceStore(records)

    selected = store.filter(task_id="task-msft", run_id="run-msft", company_id=15, evidence_role="target")

    assert [row.evidence_id for row in selected] == ["target_ev"]


def test_retrieve_evidence_skips_corrupt_parquet_file(tmp_path: Path):
    curated = tmp_path / "curated"
    _write_curated_inputs(curated)
    (curated / "broken.parquet").write_text("not a parquet file", encoding="utf-8")

    hits, meta = retrieve_evidence_with_mode(
        query="gross margin revenue",
        topk=3,
        curated_dir=str(curated),
        ranking_mode="bm25",
        log=False,
    )

    assert hits
    assert hits[0]["symbol"] == "AAPL"
    assert meta["loaded_file_count"] == 1
    assert len(meta["skipped_files"]) == 1
    assert "broken.parquet" in meta["skipped_files"][0]
    assert meta["load_errors"]
    assert "bm25_score" in hits[0]
    assert meta["score_min"] is not None


def test_retrieve_evidence_uses_json_when_all_parquet_files_are_corrupt(tmp_path: Path):
    curated = tmp_path / "curated"
    curated.mkdir()
    (curated / "broken.parquet").write_text("not a parquet file", encoding="utf-8")
    (curated / "fallback.json").write_text(
        """
[
  {
    "sample_id": "fallback-1",
    "source_type": "company_profile",
    "symbol": "TSLA",
    "period": "2026Q1",
    "title": "Tesla profile",
    "publish_time": "2026-04-01",
    "content": "Tesla designs electric vehicles and energy products.",
    "source_url": "https://example.com/tsla",
    "trust_level": "medium"
  }
]
""".strip(),
        encoding="utf-8",
    )

    hits, meta = retrieve_evidence_with_mode(
        query="electric vehicles",
        topk=3,
        curated_dir=str(curated),
        ranking_mode="hybrid_rerank",
        log=False,
    )

    assert hits
    assert hits[0]["sample_id"] == "fallback-1"
    assert meta["retrieval_available"] is True
    assert meta["fallback_json_file_count"] == 1
    assert meta["load_errors"][0]["error_type"] == "parquet_corrupt_or_incompatible"


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


def test_retrieve_evidence_isolated_vector_index_ignores_global_collection(tmp_path: Path):
    global_vector_path = tmp_path / "global_vector_db"
    global_index = ChromaIndex(persistent_path=str(global_vector_path))
    global_index.add_records(
        [
            EvidenceRecord.from_dict(
                {
                    "sample_id": "global_pollution",
                    "source_type": "news",
                    "symbol": "POLLUTE",
                    "period": "FY2024",
                    "title": "Unrelated global record",
                    "publish_time": "2026-01-01",
                    "content": "revenue profit cash flow risk valuation official annual report",
                    "source_url": "https://example.com/global",
                    "trust_level": "low",
                }
            )
        ]
    )

    curated = tmp_path / "curated"
    _write_curated_inputs(curated)
    hits, meta = retrieve_evidence_with_mode(
        query="revenue profit cash flow risk valuation official annual report",
        topk=5,
        curated_dir=str(curated),
        symbol="AAPL",
        period="2025Q4",
        ranking_mode="hybrid",
        vector_persistent_path=None,
        log=False,
    )

    assert hits
    assert {hit["symbol"] for hit in hits} == {"AAPL"}
    assert "global_pollution" not in {hit.get("sample_id") for hit in hits}
    assert meta["vector_backend"] in {"memory", "chromadb"}
    assert meta["vector_score_max"] is not None


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
