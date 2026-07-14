import json
from types import SimpleNamespace

from src.evaluation.evidence_retrieval_attribution import build_evidence_retrieval_attribution
from src.rag.dense_retriever import DenseRetriever
from src.rag.rrf_fusion import reciprocal_rank_fusion
from src.retrieval.chunking import chunk_record
from src.retrieval.retrieve import _isolated_collection_name
from src.services.document_service import _chunks_to_evidence, _TextChunk


def test_generic_chunks_emit_runtime_identity_contracts():
    chunks = chunk_record(
        {
            "evidence_id": "ev_parent",
            "symbol": "600519.SS",
            "period": "FY2024",
            "source_type": "cninfo_announcement",
            "source_url": "https://www.cninfo.com.cn/report.pdf",
            "title": "贵州茅台年报",
            "content": "公司收入保持增长。\n\n经营现金流支持利润质量。",
        },
        max_chars=20,
    )

    rows = [chunk.to_dict() for chunk in chunks]
    assert len(rows) == 2
    assert len({row["identity_key"] for row in rows}) == 2
    assert len({row["document_key"] for row in rows}) == 1
    assert all(row["period_spec"]["match_status"] == "matched" for row in rows)
    assert all(row["metadata"]["parent_identity_key"] for row in rows)


def test_rrf_merges_component_hits_by_business_identity():
    hits = reciprocal_rank_fusion(
        [
            [{"identity_key": "evi_same", "evidence_id": "bm25_id", "bm25_score": 1.0}],
            [{"identity_key": "evi_same", "evidence_id": "dense_id", "vector_score": 0.8}],
        ],
        topk=5,
    )

    assert len(hits) == 1
    assert hits[0]["rank_sources"] == ["bm25", "dense"]


def test_default_collection_is_isolated_by_symbol_and_period():
    aapl = _isolated_collection_name("data/curated", symbol="AAPL", period="FY2024")
    tsla = _isolated_collection_name("data/curated", symbol="TSLA", period="FY2024")
    aapl_next = _isolated_collection_name("data/curated", symbol="AAPL", period="FY2025")

    assert len({aapl, tsla, aapl_next}) == 3
    assert all(name.startswith("finsight_task_") for name in (aapl, tsla, aapl_next))


def test_dense_hash_embedding_is_reported_as_degraded():
    class HashIndex:
        backend = "memory"
        embedding_backend = "hash_fallback"

        def add_records(self, records):
            self.records = records

        def search(self, query, topk):
            return [{**self.records[0].to_dict(), "vector_score": 0.4}]

    record = SimpleNamespace(to_dict=lambda: {"evidence_id": "ev1"})
    hits, meta = DenseRetriever([record], index_factory=HashIndex).search("revenue")

    assert hits
    assert meta["degraded"] is True
    assert meta["semantic_available"] is False
    assert meta["embedding_backend"] == "hash_fallback"


def test_attribution_does_not_treat_hash_score_as_semantic_similarity(tmp_path):
    outputs = tmp_path / "outputs"
    reports = tmp_path / "reports"
    outputs.mkdir()
    reports.mkdir()
    (outputs / "search_meta.json").write_text(
        json.dumps(
            {
                "engine_meta": {
                    "local_evidence": {
                        "source_record_count": 1,
                        "candidate_count": 1,
                        "returned_hit_count": 1,
                        "vector_hit_count": 1,
                        "vector_score_max": 0.4,
                        "embedding_backend": "hash_fallback",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    artifact = build_evidence_retrieval_attribution(outputs, reports_dir=reports)

    assert artifact["retrieval_summary"]["similarity_status"] == "hash_fallback"
    assert artifact["retrieval_summary"]["semantic_vector_available"] is False
    assert "similarity_hash_fallback" in artifact["section_results"]["valuation"]["root_causes"]


def test_manual_document_chunks_share_document_identity():
    document = SimpleNamespace(
        id=7,
        doc_type="manual_text",
        report_period="FY2024",
        source_url="https://example.com/report",
        title="用户导入年报",
    )
    company = SimpleNamespace(id=3, name="测试公司", symbol="AAPL", market="us")
    items = _chunks_to_evidence(
        [_TextChunk(content="Revenue evidence", index=0), _TextChunk(content="Risk evidence", index=1)],
        document=document,
        company=company,
    )

    assert len({item.metadata_json["identity_key"] for item in items}) == 2
    assert len({item.metadata_json["document_key"] for item in items}) == 1
    assert all(item.metadata_json["period_spec"]["match_status"] == "matched" for item in items)
