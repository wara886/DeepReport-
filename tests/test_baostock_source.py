from types import SimpleNamespace

from src.data.baostock_source import fetch_baostock_financials


class Result:
    error_code = "0"
    error_msg = ""
    fields = ["code", "pubDate", "statDate", "roeAvg"]

    def __init__(self):
        self.done = False

    def next(self):
        if self.done:
            return False
        self.done = True
        return True

    def get_row_data(self):
        return ["sh.600519", "2025-04-03", "2024-12-31", "0.31"]


class Client:
    def login(self):
        return SimpleNamespace(error_code="0", error_msg="success")

    def logout(self):
        return None

    def __getattr__(self, name):
        if name.startswith("query_"):
            return lambda **_kwargs: Result()
        raise AttributeError(name)


def test_baostock_source_builds_secondary_period_matched_records():
    result = fetch_baostock_financials(symbol="600519.SS", period="FY2024", client=Client())

    assert result["meta"]["record_count"] == 6
    assert result["hits"][0]["source_type"] == "baostock_financials"
    assert result["hits"][0]["source_authority"] == "third_party_structured"
    assert result["hits"][0]["authority_level"] == "secondary"
    assert result["hits"][0]["period"] == "FY2024"
