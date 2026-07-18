from src.retrieval.chunking import chunk_record, chunk_records
from src.retrieval.retrieve import retrieve_evidence_with_mode


def test_chunk_record_creates_paragraph_and_metric_chunks_with_lineage():
    record = {
        "sample_id": "aapl_fin_1",
        "source_type": "financials",
        "symbol": "AAPL",
        "period": "2025Q4",
        "title": "AAPL financial summary",
        "publish_time": "2026-01-30",
        "content": "Revenue 126.3B and gross margin 46.8%. Operating cash flow was 38.1B.",
        "source_url": "https://example.com/aapl",
        "trust_level": "high",
        "metadata": {
            "revenue_billion": 126.3,
            "gross_margin_pct": 46.8,
            "operating_cash_flow_billion": 38.1,
            "table_id": "income_statement",
            "row_id": "fy2025q4",
            "cell_ref": "B2",
        },
    }

    chunks = chunk_record(record)
    metric_chunks = [chunk for chunk in chunks if chunk.chunk_type == "metric"]

    assert any(chunk.chunk_type == "paragraph" for chunk in chunks)
    assert {chunk.metric_name for chunk in metric_chunks} >= {
        "revenue_billion",
        "gross_margin_pct",
        "operating_cash_flow_billion",
    }
    assert all(chunk.parent_sample_id == "aapl_fin_1" for chunk in chunks)
    assert metric_chunks[0].source_url == "https://example.com/aapl"
    assert metric_chunks[0].table_id == "income_statement"
    assert metric_chunks[0].row_id == "fy2025q4"
    assert metric_chunks[0].cell_refs == ["B2"]


def test_chunk_records_creates_table_row_chunks():
    chunks = chunk_records(
        [
            {
                "sample_id": "filing_1",
                "source_type": "filing",
                "symbol": "AAPL",
                "period": "2025Q4",
                "title": "AAPL 10-Q table",
                "content": "Selected financial table.",
                "source_url": "https://example.com/aapl-10q",
                "trust_level": "high",
                "metadata": {
                    "table_rows": [
                        {
                            "table_id": "cash_flow",
                            "row_id": "r1",
                            "metric": "free_cash_flow_billion",
                            "value": 33.1,
                            "cell_refs": ["C4"],
                        }
                    ]
                },
            }
        ]
    )

    table_chunks = [chunk for chunk in chunks if chunk.chunk_type == "table_row"]

    assert len(table_chunks) == 1
    assert table_chunks[0].table_id == "cash_flow"
    assert table_chunks[0].row_id == "r1"
    assert table_chunks[0].numeric_values["value"] == 33.1


def test_chunk_record_is_idempotent_for_existing_chunk_metadata():
    first = chunk_record({
        "sample_id": "aapl_financials",
        "source_type": "market_api",
        "symbol": "AAPL",
        "period": "FY2024",
        "content": "Revenue 391.035B and net income 93.736B.",
        "metadata": {"financials": {"income_history": [{"end_date": "2024-09-30"}]}},
    })[0].to_dict()

    second = chunk_record(first)[0].to_dict()
    third = chunk_record(second)[0].to_dict()

    assert second["evidence_id"] == first["evidence_id"]
    assert third["evidence_id"] == first["evidence_id"]
    assert second["metadata"] == first["metadata"]
    assert third["metadata"] == first["metadata"]


def test_retrieval_can_rank_metric_chunks_from_curated_dir(tmp_path):
    import pandas as pd

    curated = tmp_path / "curated"
    curated.mkdir()
    pd.DataFrame(
        [
            {
                "sample_id": "s1",
                "source_type": "financials",
                "symbol": "AAPL",
                "period": "2025Q4",
                "title": "AAPL 10-Q summary",
                "publish_time": "2026-01-30",
                "content": "Revenue 126.3B and gross margin 46.8%.",
                "source_url": "https://example.com/aapl",
                "trust_level": "high",
            }
        ]
    ).to_parquet(curated / "sample.parquet", index=False)

    hits, meta = retrieve_evidence_with_mode(
        query="gross margin 46.8",
        topk=3,
        curated_dir=str(curated),
        ranking_mode="bm25",
        use_chunks=True,
        log=False,
    )

    assert hits
    assert hits[0]["chunk_type"] == "paragraph"
    assert hits[0]["parent_sample_id"] == "s1"
    assert "numeric_values" in hits[0]
    assert meta["chunking_enabled"] is True
    assert meta["chunk_count"] >= 1


def test_vector_retrieval_accepts_chunk_nested_metadata(tmp_path):
    import pandas as pd

    curated = tmp_path / "curated"
    curated.mkdir()
    pd.DataFrame(
        [
            {
                "sample_id": "s1",
                "source_type": "financials",
                "symbol": "AAPL",
                "period": "2025Q4",
                "title": "AAPL metric table",
                "publish_time": "2026-01-30",
                "content": "Gross margin 46.8%.",
                "source_url": "https://example.com/aapl",
                "trust_level": "high",
            }
        ]
    ).to_parquet(curated / "sample.parquet", index=False)

    hits, meta = retrieve_evidence_with_mode(
        query="gross margin",
        topk=2,
        curated_dir=str(curated),
        ranking_mode="vector",
        use_chunks=True,
        log=False,
    )

    assert hits
    assert meta["mode"] == "vector"
    assert meta["chunking_enabled"] is True
