import json

from src.data.hkex_official_source import fetch_hkex_official_announcements


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


def test_hkex_direct_source_filters_symbol_period_and_pdf(monkeypatch):
    directory = json.dumps([{"c": "700", "i": "123", "n": "Tencent"}]).encode()
    rows = [
        {"STOCK_CODE": "00700", "TITLE": "ANNUAL REPORT 2025", "FILE_TYPE": "PDF", "FILE_LINK": "/tencent.pdf", "DATE_TIME": "2026-04-01"},
        {"STOCK_CODE": "00020", "TITLE": "ANNUAL REPORT 2025", "FILE_TYPE": "PDF", "FILE_LINK": "/wrong.pdf", "DATE_TIME": "2026-04-01"},
        {"STOCK_CODE": "00700", "TITLE": "ANNUAL REPORT 2024", "FILE_TYPE": "PDF", "FILE_LINK": "/old.pdf", "DATE_TIME": "2025-04-01"},
    ]
    search = json.dumps({"result": json.dumps(rows)}).encode()
    responses = iter([FakeResponse(directory), FakeResponse(search)])
    monkeypatch.setattr("src.data.hkex_official_source.request.urlopen", lambda *_args, **_kwargs: next(responses))

    result = fetch_hkex_official_announcements(symbol="0700.HK", period="FY2025")

    assert result["meta"]["mode"] == "hkex_official"
    assert result["meta"]["result_count"] == 1
    assert result["hits"][0]["source_url"] == "https://www1.hkexnews.hk/tencent.pdf"
    assert result["hits"][0]["source_authority"] == "official"
