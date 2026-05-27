import json

from src.data.independent_sources import SourcePayload
from src.evaluation.formal_evidence_staging import _normalize_publish_time, stage_formal_evidence
from src.search.search_manager import _announcement_date_range, _filter_period_announcement_hits, _select_financial_row_for_period, _target_report_date


def test_fy2024_period_routes_use_requested_year():
    assert _announcement_date_range("FY2024") == ("2024-01-01", "2025-12-31")
    assert _target_report_date("FY2024") == "2024-12-31"
    filtered = _filter_period_announcement_hits(
        [
            {"title": "贵州茅台2024年年度报告"},
            {"title": "贵州茅台2023年年度报告"},
        ],
        "FY2024",
    )
    assert filtered == [{"title": "贵州茅台2024年年度报告"}]
    assert _normalize_publish_time("1743609600000", timezone_offset_hours=8) == "2025-04-03"


def test_annual_evidence_selection_does_not_fallback_to_another_period():
    assert _filter_period_announcement_hits([{"title": "Company 2023 Annual Report"}], "FY2024") == []
    assert _select_financial_row_for_period([{"REPORT_DATE": "2025-12-31", "TOTAL_ASSETS": 1}], "FY2024") == {}


def test_staging_writes_strict_us_and_cn_evidence_but_blocks_hk(monkeypatch, tmp_path):
    config_path = tmp_path / "formal.yaml"
    config_path.write_text(
        """
benchmark:
  id: staging_test
  period: FY2024
  variants:
    - {id: direct_llm}
    - {id: single_agent_rag}
    - {id: multi_agent_rag}
  cases:
    - {case_id: us_aapl, market: US, company_name: Apple, canonical_symbol: AAPL}
    - {case_id: cna_moutai, market: CN-A, company_name: Moutai, canonical_symbol: 600519.SS}
    - {case_id: hk_tencent, market: HK, company_name: Tencent, canonical_symbol: 0700.HK}
""".strip(),
        encoding="utf-8",
    )

    def fake_sec(symbol, period, config_path):
        assert period == "FY2024"
        metrics = {
            "Revenues": {"value": 1, "fy": 2024, "fp": "FY", "form": "10-K"},
            "NetIncomeLoss": {"value": 1, "fy": 2024, "fp": "FY", "form": "10-K"},
            "NetCashProvidedByUsedInOperatingActivities": {"value": 1, "fy": 2024, "fp": "FY", "form": "10-K"},
        }
        return SourcePayload(
            hits=[_evidence("sec_aapl", symbol, "sec_companyfacts", metadata={"metrics": metrics})],
            meta={"mode": "sec_companyfacts", "record_count": 1},
        )

    def fake_cninfo(**kwargs):
        return {"hits": [_evidence("cninfo_report", "600519.SS", "cninfo_announcement", title="贵州茅台2024年年度报告")], "meta": {"record_count": 1}}

    def fake_financials(**kwargs):
        return {
            "hits": [
                _evidence(
                    f"em_{kind}",
                    "600519.SS",
                    "eastmoney_financials",
                    metadata={"table_type": kind, "raw": {"REPORT_DATE": "2024-12-31 00:00:00"}},
                )
                for kind in ("income", "balance", "cashflow")
            ],
            "meta": {"record_count": 3},
        }

    monkeypatch.setattr("src.evaluation.formal_evidence_staging.fetch_sec_companyfacts_evidence", fake_sec)
    monkeypatch.setattr("src.evaluation.formal_evidence_staging.cninfo_announcement_search", fake_cninfo)
    monkeypatch.setattr("src.evaluation.formal_evidence_staging.eastmoney_financials_search", fake_financials)
    monkeypatch.setattr("src.evaluation.formal_evidence_staging._fetch_hkex_stock_directory", lambda: {})
    monkeypatch.setattr(
        "src.evaluation.formal_evidence_staging._acquire_hk_case",
        lambda case, period, directory: ([], ["no verified HKEX annual report"], [{"source": "hkex_title_search"}]),
    )

    manifest = stage_formal_evidence(config_path=config_path, source_root=tmp_path / "sources")

    assert manifest["staged_case_count"] == 2
    assert manifest["blocked_case_count"] == 1
    assert (tmp_path / "sources" / "us_aapl" / "evidence.jsonl").exists()
    assert (tmp_path / "sources" / "cna_moutai" / "evidence.jsonl").exists()
    assert not (tmp_path / "sources" / "hk_tencent" / "evidence.jsonl").exists()
    assert json.loads((tmp_path / "sources" / "acquisition_manifest.json").read_text(encoding="utf-8"))["complete"] is False


def test_staging_accepts_hkex_annual_report_with_extracted_financial_text(monkeypatch, tmp_path):
    config_path = tmp_path / "formal.yaml"
    config_path.write_text(
        """
benchmark:
  id: hk_staging_test
  period: FY2024
  variants:
    - {id: direct_llm}
    - {id: single_agent_rag}
    - {id: multi_agent_rag}
  cases:
    - {case_id: hk_tencent, market: HK, company_name: Tencent, canonical_symbol: 0700.HK}
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "src.evaluation.formal_evidence_staging._fetch_hkex_stock_directory",
        lambda: {"00700": {"i": 7609, "c": "00700", "n": "TENCENT"}},
    )
    monkeypatch.setattr(
        "src.evaluation.formal_evidence_staging._query_hkex_documents",
        lambda stock_id, period: [
            {
                "STOCK_CODE": "00700<br/>80700",
                "STOCK_NAME": "TENCENT<br/>TENCENT-R",
                "TITLE": "ANNUAL REPORT 2024",
                "DATE_TIME": "08/04/2025 17:02",
                "FILE_TYPE": "PDF",
                "FILE_LINK": "/listedco/report.pdf",
                "NEWS_ID": "11618397",
            }
        ],
    )
    monkeypatch.setattr(
        "src.evaluation.formal_evidence_staging._download_and_extract_hkex_pdf",
        lambda source_url, period: {
            "content": "[PDF page 4] Revenue for the year ended 31 December 2024 was RMB660.3 billion.",
            "pages": [4],
            "page_count": 274,
            "pdf_sha256": "abc123",
        },
    )

    manifest = stage_formal_evidence(config_path=config_path, source_root=tmp_path / "sources")
    evidence = json.loads((tmp_path / "sources" / "hk_tencent" / "evidence.jsonl").read_text(encoding="utf-8").splitlines()[0])

    assert manifest["complete"] is True
    assert evidence["source_type"] == "hkex_annual_report"
    assert evidence["source_authority"] == "official"
    assert evidence["metadata"]["pdf_sha256"] == "abc123"
    assert evidence["publish_time"] == "2025-04-08"


def _evidence(evidence_id, symbol, source_type, title="Evidence", metadata=None):
    return {
        "evidence_id": evidence_id,
        "source_type": source_type,
        "title": title,
        "source_url": "https://example.com/evidence",
        "publish_time": "2025-04-01",
        "content": title,
        "symbol": symbol,
        "period": "FY2024",
        "trust_level": "high",
        "metadata": metadata or {},
    }
