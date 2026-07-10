import json
from pathlib import Path

from src.rag.hybrid_retriever import HybridRetriever
from src.retrieval.canonical_chunks import normalize_retrieval_record
from src.retrieval.evidence_store import EvidenceRecord, EvidenceStore


def test_pdf_and_table_chunks_normalize_into_metadata_rich_records():
    pdf_chunk = normalize_retrieval_record(
        {
            "chunk_id": "pdf_risk_001",
            "symbol": "600519.SS",
            "period": "FY2024",
            "source_type": "cninfo_announcement",
            "source_title": "贵州茅台 2024 年报",
            "section_type": "risk_factors",
            "section_title": "风险因素",
            "block_type": "paragraph",
            "text": "公司面临渠道库存、需求波动和监管政策变化等风险。",
            "pages": [42],
        }
    )

    record = EvidenceRecord.from_dict(pdf_chunk)

    assert record.sample_id == "pdf_risk_001"
    assert record.chunk_type == "paragraph"
    assert record.section_type == "risk_factors"
    assert record.page_no == 42
    assert record.pages == [42]
    assert "风险披露" in record.meta_tags
    assert "需求波动" in record.meta_tags
    assert "risk_factors" in record.searchable_text
    assert "风险因素" in record.searchable_text


def test_hybrid_retriever_uses_canonical_pdf_chunk_metadata(tmp_path: Path):
    curated = tmp_path / "curated"
    curated.mkdir()
    records = [
        {
            "chunk_id": "pdf_business_001",
            "symbol": "0700.HK",
            "period": "FY2024",
            "source_type": "hkex_announcement",
            "source_title": "腾讯控股 2024 年报",
            "section_type": "business_overview",
            "section_title": "业务概览",
            "block_type": "paragraph",
            "text": "增值服务、网络广告和金融科技业务构成主要收入来源。",
            "pages": [18],
        },
        {
            "chunk_id": "pdf_fin_table_001",
            "symbol": "0700.HK",
            "period": "FY2024",
            "source_type": "hkex_announcement",
            "source_title": "腾讯控股 2024 年报",
            "section_type": "financial_statements",
            "section_title": "综合收益表",
            "block_type": "table_row",
            "table_id": "income_statement",
            "row_id": "revenue",
            "text": "Revenue RMB660.3 billion, gross profit improved and operating cash flow remained positive.",
            "pages": [220],
        },
        {
            "chunk_id": "pdf_risk_001",
            "symbol": "0700.HK",
            "period": "FY2024",
            "source_type": "hkex_announcement",
            "source_title": "腾讯控股 2024 年报",
            "section_type": "risk_factors",
            "section_title": "风险因素",
            "block_type": "paragraph",
            "text": "Regulatory policy changes and demand volatility may affect advertising and gaming revenue.",
            "pages": [77],
        },
    ]
    (curated / "pdf_chunks.json").write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")

    store = EvidenceStore.from_curated_parquet(curated)
    assert len(store.records) == 3
    assert any(record.section_type == "financial_statements" and record.chunk_type == "table_row" for record in store.records)

    financial_hits, financial_meta = HybridRetriever(curated_dir=str(curated)).search(
        "财务报表 revenue gross profit cash flow",
        topk=2,
        symbol="0700.HK",
        period="FY2024",
        mode="hybrid",
    )
    assert financial_hits
    assert financial_hits[0]["section_type"] == "financial_statements"
    assert financial_hits[0]["chunk_type"] == "table_row"
    assert "收入表现" in financial_hits[0]["meta_tags"]
    assert financial_meta["coverage"]["quality_ready"] is True

    risk_hits, _ = HybridRetriever(curated_dir=str(curated)).search(
        "风险披露 regulatory demand volatility",
        topk=2,
        symbol="0700.HK",
        period="FY2024",
        mode="hybrid",
    )
    assert risk_hits
    assert risk_hits[0]["section_type"] == "risk_factors"
    assert "风险披露" in risk_hits[0]["meta_tags"]
