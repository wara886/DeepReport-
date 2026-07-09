import json
from pathlib import Path

from src.rag.hybrid_retriever import HybridRetriever
from src.retrieval.retrieve import retrieve_evidence_with_mode


def write_curated_json(root: Path) -> None:
    root.mkdir(parents=True)
    (root / "records.json").write_text(
        json.dumps(
            [
                {
                    "sample_id": "aapl-revenue",
                    "evidence_id": "ev_aapl_revenue",
                    "source_type": "financials",
                    "symbol": "AAPL",
                    "period": "FY2024",
                    "title": "AAPL FY2024 revenue",
                    "publish_time": "2025-10-30",
                    "content": "Revenue and gross margin improved in FY2024.",
                    "source_url": "https://example.com/aapl",
                    "trust_level": "official",
                },
                {
                    "sample_id": "msft-risk",
                    "evidence_id": "ev_msft_risk",
                    "source_type": "news",
                    "symbol": "MSFT",
                    "period": "FY2024",
                    "title": "MSFT risk",
                    "publish_time": "2025-10-30",
                    "content": "Enterprise demand stayed stable.",
                    "source_url": "https://example.com/msft",
                    "trust_level": "secondary",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_hybrid_retriever_contract_returns_hits_and_meta(tmp_path):
    curated = tmp_path / "curated"
    write_curated_json(curated)

    hits, meta = HybridRetriever(curated_dir=str(curated)).search("revenue gross margin", topk=2, mode="hybrid")

    assert hits
    assert hits[0]["symbol"] == "AAPL"
    assert hits[0]["final_score"] >= 0
    assert meta["mode"] == "hybrid"
    assert meta["mode_effective"] in {"hybrid", "bm25"}
    assert meta["bm25_hit_count"] >= 1
    assert meta["returned_hit_count"] >= 1
    assert meta["retrieval_available"] is True
    assert meta["coverage"]["evidence_ready"] is True
    assert meta["coverage"]["returned_count"] == meta["returned_hit_count"]
    assert "financials" in meta["coverage"]["returned_sources"]
    assert meta["coverage"]["summary"]


def test_legacy_retrieve_evidence_with_mode_uses_hybrid_layer(tmp_path):
    curated = tmp_path / "curated"
    write_curated_json(curated)

    hits, meta = retrieve_evidence_with_mode(
        query="revenue gross margin",
        topk=2,
        curated_dir=str(curated),
        ranking_mode="hybrid",
        log=False,
    )

    assert hits
    assert hits[0]["symbol"] == "AAPL"
    assert meta["mode"] == "hybrid"
    assert "dense_hit_count" in meta
    assert "vector_hit_count" in meta
    assert meta["coverage"]["evidence_ready"] is True
