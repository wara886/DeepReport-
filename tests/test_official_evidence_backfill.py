import json

from src.data.official_evidence_archive import build_official_evidence_artifacts
from src.data.official_evidence_backfill import execute_official_evidence_backfill


def test_backfill_executor_turns_cn_plan_into_official_coverage(tmp_path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    initial = build_official_evidence_artifacts([], symbol="600519.SS", period="FY2024", tables=[])
    (outputs / "official_evidence_backfill_plan.json").write_text(
        json.dumps(initial["official_evidence_backfill_plan"], ensure_ascii=False),
        encoding="utf-8",
    )

    result = execute_official_evidence_backfill(
        symbol="600519.SS",
        period="FY2024",
        output_dir=outputs,
        search_manager=FakeSearchManager(),
    )
    coverage = json.loads((outputs / "evidence_coverage.json").read_text(encoding="utf-8"))
    tables = json.loads((outputs / "tables.json").read_text(encoding="utf-8"))

    assert result["acquired_record_count"] >= 4
    assert coverage["formal_delivery_allowed"] is True
    assert coverage["has_three_statements"] is True
    assert coverage["period_matched_official_record_count"] >= 1
    assert {table["table_type"] for table in tables} == {"income_statement", "balance_sheet", "cash_flow_statement"}


def test_backfill_executor_uses_pdf_page_anchored_statement_tables(monkeypatch, tmp_path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    initial = build_official_evidence_artifacts([], symbol="0700.HK", period="FY2024", tables=[])
    (outputs / "official_evidence_backfill_plan.json").write_text(
        json.dumps(initial["official_evidence_backfill_plan"], ensure_ascii=False),
        encoding="utf-8",
    )

    def fake_pdf_artifacts(records, cache_dir, max_pdfs=1, max_pages=20):
        return {
            "pdf_manifest": [{"status": "cached", "source_url": "https://www1.hkexnews.hk/report.pdf"}],
            "pdf_sections": [
                {
                    "section_id": "financial_page",
                    "evidence_id": "hkex_annual",
                    "source_url": "https://www1.hkexnews.hk/report.pdf",
                    "page": 88,
                    "section_type": "financial_statements",
                    "snippet": "Consolidated income statement, balance sheet and cash flow statement.",
                    "extraction_method": "test",
                }
            ],
            "pdf_tables": [
                _pdf_table("income_statement", "revenue"),
                _pdf_table("balance_sheet", "total_assets"),
                _pdf_table("cash_flow_statement", "operating_cash_flow"),
            ],
            "meta": {"cached_pdf_count": 1, "statement_table_count": 3},
        }

    monkeypatch.setattr("src.data.official_evidence_backfill.build_pdf_artifacts", fake_pdf_artifacts)

    result = execute_official_evidence_backfill(
        symbol="0700.HK",
        period="FY2024",
        output_dir=outputs,
        search_manager=FakeSearchManager(hkex_empty=False),
    )
    coverage = json.loads((outputs / "evidence_coverage.json").read_text(encoding="utf-8"))

    assert result["pdf_record_count"] == 4
    assert coverage["pdf_page_anchor_count"] >= 1
    assert coverage["has_official_pdf_three_statements"] is True
    assert coverage["formal_delivery_allowed"] is True


def test_backfill_executor_keeps_hk_formal_blocked_without_official_announcement(tmp_path):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    initial = build_official_evidence_artifacts([], symbol="0700.HK", period="FY2024", tables=[])
    (outputs / "official_evidence_backfill_plan.json").write_text(
        json.dumps(initial["official_evidence_backfill_plan"], ensure_ascii=False),
        encoding="utf-8",
    )

    result = execute_official_evidence_backfill(
        symbol="0700.HK",
        period="FY2024",
        output_dir=outputs,
        search_manager=FakeSearchManager(hkex_empty=True),
    )
    coverage = json.loads((outputs / "evidence_coverage.json").read_text(encoding="utf-8"))

    assert any(item["source_key"] == "hkex_announcements" and item["status"] == "empty" for item in result["attempts"])
    assert coverage["formal_delivery_allowed"] is False
    assert "period_matched_official_filing" in coverage["missing_requirements"]


class FakeSearchManager:
    def __init__(self, *, hkex_empty=False):
        self.hkex_empty = hkex_empty

    def search(self, query, topk=10, engines=None, **kwargs):
        engine = engines[0]
        symbol = kwargs.get("symbol", "")
        period = kwargs.get("period", "")
        if engine == "cninfo_announcements":
            return _payload(
                engine,
                [
                    {
                        "evidence_id": "cninfo_annual",
                        "symbol": symbol,
                        "period": period,
                        "source_type": "cninfo_announcement",
                        "source_url": "http://static.cninfo.com.cn/report.pdf",
                        "title": "贵州茅台2024年年度报告",
                        "content": "CNINFO official annual report",
                        "metadata": {"provider": "CNINFO", "page": 1},
                    }
                ],
            )
        if engine == "eastmoney_financials":
            return _payload(engine, [_eastmoney_hit(symbol, period, kind) for kind in ("income", "balance", "cashflow")])
        if engine == "hkex_announcements":
            return _payload(
                engine,
                []
                if self.hkex_empty
                else [
                    {
                        "evidence_id": "hkex_annual",
                        "symbol": symbol,
                        "period": period,
                        "source_type": "hkex_annual_report",
                        "source_url": "https://www1.hkexnews.hk/report.pdf",
                        "title": "Annual Report 2024",
                        "content": "HKEX annual report",
                        "metadata": {"provider": "HKEX", "page": 1},
                    }
                ],
            )
        if engine == "hk_financials":
            return _payload(engine, [])
        return _payload(engine, [])


def _payload(engine, rows):
    return {
        "hits": [{"raw": row} for row in rows],
        "meta": {"engine_meta": {engine: {"record_count": len(rows)}}},
    }


def _pdf_table(table_type, line_item):
    return {
        "table_id": f"pdf_{table_type}",
        "evidence_id": "hkex_annual",
        "source_url": "https://www1.hkexnews.hk/report.pdf",
        "page": 88,
        "table_type": table_type,
        "rows": [{"statement": table_type, "line_item": line_item, "value": 100.0}],
        "unit": "millions",
        "currency": "CNY",
        "extraction_method": "test_pdf_table",
    }


def _eastmoney_hit(symbol, period, table_type):
    raw_by_type = {
        "income": {
            "REPORT_DATE": "2024-12-31 00:00:00",
            "TOTAL_OPERATE_INCOME": 100.0,
            "PARENT_NETPROFIT": 50.0,
            "TOTAL_OPERATE_COST": 35.0,
        },
        "balance": {
            "REPORT_DATE": "2024-12-31 00:00:00",
            "TOTAL_ASSETS": 300.0,
            "TOTAL_LIABILITIES": 80.0,
            "TOTAL_EQUITY": 220.0,
        },
        "cashflow": {
            "REPORT_DATE": "2024-12-31 00:00:00",
            "NETCASH_OPERATE": 70.0,
            "CONSTRUCT_LONG_ASSET_PAY_CASH": 10.0,
        },
    }
    return {
        "evidence_id": f"eastmoney_{table_type}",
        "symbol": symbol,
        "period": period,
        "source_type": "eastmoney_financials",
        "title": f"{symbol} {table_type}",
        "content": f"{table_type} table",
        "source_url": f"https://data.eastmoney.com/bbsj/{symbol}.html",
        "metadata": {"provider": "Eastmoney", "table_type": table_type, "raw": raw_by_type[table_type]},
    }
