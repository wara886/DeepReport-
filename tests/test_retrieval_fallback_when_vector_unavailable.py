import json
from pathlib import Path

from src.rag.hybrid_retriever import HybridRetriever


class BrokenDenseRetriever:
    def __init__(self, records):
        self.records = records

    def search(self, query, *, topk):
        return [], {"backend": "disabled", "available": False, "hit_count": 0, "error": "vector unavailable"}


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
                    "content": "Revenue improved and gross margin expanded.",
                    "source_url": "https://example.com/aapl",
                    "trust_level": "official",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_hybrid_retriever_falls_back_to_bm25_when_vector_unavailable(tmp_path):
    curated = tmp_path / "curated"
    write_curated_json(curated)

    hits, meta = HybridRetriever(curated_dir=str(curated), dense_retriever_cls=BrokenDenseRetriever).search(
        "revenue margin",
        topk=3,
        mode="hybrid",
    )

    assert hits
    assert hits[0]["evidence_id"] == "ev_aapl_revenue"
    assert meta["dense"]["available"] is False
    assert meta["dense"]["error"] == "vector unavailable"
    assert meta["mode_effective"] == "bm25"
    assert meta["fallback_used"] is True
