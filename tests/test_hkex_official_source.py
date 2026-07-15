import json

import pytest

from src.data.hkex_official_source import _read_response_bytes, fetch_hkex_official_announcements


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.consumed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size=-1):
        if self.consumed:
            return b""
        self.consumed = True
        return self.payload


def test_hkex_response_reader_enforces_total_deadline(monkeypatch):
    class StreamingResponse:
        def read(self, _size):
            return b"x"

    ticks = iter([10.0, 10.5, 11.1])
    monkeypatch.setattr("src.data.hkex_official_source.time.monotonic", lambda: next(ticks))

    with pytest.raises(RuntimeError, match="request timed out"):
        _read_response_bytes(StreamingResponse(), timeout=1.0)


def test_hkex_direct_source_filters_symbol_period_and_pdf(monkeypatch):
    directory = json.dumps([{"c": "700", "i": "123", "n": "Tencent"}]).encode()
    rows = [
        {"STOCK_CODE": "00700", "TITLE": "ANNUAL REPORT 2025", "FILE_TYPE": "PDF", "FILE_LINK": "/tencent.pdf", "DATE_TIME": "01/04/2026 17:02"},
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
    assert result["hits"][0]["publish_time"] == "2026-04-01"
    assert result["hits"][0]["source_authority"] == "official"
