from src.schemas.runtime_contracts import (
    build_company_identity,
    build_period_spec,
    normalize_evidence_record,
    normalize_metric_candidate,
)


def test_company_identity_normalizes_three_markets():
    assert build_company_identity("600519.SH")["symbol"] == "600519.SS"
    assert build_company_identity("0700.HK")["market"] == "hk"
    assert build_company_identity("aapl")["currency"] == "USD"


def test_period_spec_distinguishes_target_source_mismatch():
    matched = build_period_spec("FY2024", source_period="2024FY")
    mismatched = build_period_spec("FY2024", source_period="FY2025")
    unknown = build_period_spec("FY2024")

    assert matched["match_status"] == "matched"
    assert mismatched["match_status"] == "mismatched"
    assert unknown["match_status"] == "unknown"


def test_evidence_identity_is_stable_and_strips_tracking_parameters():
    raw = {
        "symbol": "AAPL",
        "period": "FY2024",
        "source_type": "sec_filing",
        "source_url": "https://www.sec.gov/filing?id=1&utm_source=test#page",
        "title": "Apple 2024 10-K",
        "content": "Revenue was reported for fiscal 2024.",
        "page_no": 42,
    }
    first = normalize_evidence_record(raw, task_id="task-1", target_period="FY2024")
    second = normalize_evidence_record(dict(raw), task_id="task-2", target_period="FY2024")

    assert first["identity_key"] == second["identity_key"]
    assert first["provenance"]["task_id"] != second["provenance"]["task_id"]
    assert "utm_source" not in first["source_url"]
    assert first["authority"]["source_authority"] == "official"
    assert first["period_spec"]["match_status"] == "matched"


def test_different_chunks_share_document_key_but_not_identity_key():
    base = {
        "symbol": "0700.HK",
        "period": "FY2024",
        "source_type": "hkex_announcement",
        "source_url": "https://www.hkexnews.hk/report.pdf",
        "title": "Tencent annual report",
    }
    first = normalize_evidence_record({**base, "content": "Revenue section", "page_no": 10})
    second = normalize_evidence_record({**base, "content": "Risk section", "page_no": 20})

    assert first["document_key"] == second["document_key"]
    assert first["identity_key"] != second["identity_key"]


def test_existing_business_identity_survives_renormalization():
    historical = {
        "evidence_id": "legacy_chunk_1",
        "chunk_id": "legacy_chunk_1",
        "parent_sample_id": "legacy_parent",
        "symbol": "AAPL",
        "period": "FY2024",
        "source_type": "market_api",
        "source_url": "https://finance.yahoo.com/quote/AAPL/key-statistics",
        "content": "Revenue was 391.035 billion.",
        "metadata": {
            "chunking": {"strategy": "paragraph_table_metric_v1"},
            "document_key": "doc_historical",
            "identity_key": "evi_historical",
        },
    }

    normalized = normalize_evidence_record(historical, target_period="FY2024")
    repeated = normalize_evidence_record(normalized, target_period="FY2024")

    assert normalized["document_key"] == "doc_historical"
    assert normalized["identity_key"] == "evi_historical"
    assert repeated["document_key"] == "doc_historical"
    assert repeated["identity_key"] == "evi_historical"
    assert repeated["metadata"]["identity_key"] == "evi_historical"


def test_metric_candidate_keeps_period_and_lineage_contracts():
    metric = normalize_metric_candidate(
        {
            "metric_name": "revenue",
            "value": 100,
            "currency": "HKD",
            "unit": "million",
            "period": "FY2024",
            "source_evidence_id": "ev_hk_annual",
            "source_type": "hkex_announcement",
            "source_url": "https://www.hkexnews.hk/listedco/listconews/sehk/2025/report.pdf",
        },
        symbol="0700.HK",
        target_period="FY2024",
    )

    assert metric["period_spec"]["match_status"] == "matched"
    assert metric["lineage"]["source_evidence_id"] == "ev_hk_annual"
    assert metric["authority"]["source_authority"] == "official"
    assert metric["value_context"]["currency"] == "HKD"
    assert metric["metric_id"].startswith("met_")
