import json
from datetime import date

from src.data.evidence_metadata import annotate_evidence_record
from src.data.independent_sources import (
    fetch_bls_series_evidence,
    fetch_fred_series_evidence,
    fetch_independent_evidence_bundle,
    fetch_sec_companyfacts_evidence,
)
from src.data.source_authority import grade_source_authority


def test_evidence_metadata_adds_freshness_cutoff_and_scope():
    record = annotate_evidence_record(
        {
            "source_type": "fred_series",
            "publish_time": "2026-05-01",
            "period": "2026Q2",
            "metadata": {"observation_date": "2026-04-30"},
        },
        reference_date=date(2026, 5, 16),
    )

    assert record["source_timestamp"] == "2026-05-01"
    assert record["data_cutoff"] == "2026-04-30"
    assert record["freshness_days"] == 15
    assert record["freshness_bucket"] == "fresh"
    assert record["evidence_scope"] == "macro"


def test_source_authority_marks_macro_official_statistics():
    grade = grade_source_authority(
        {
            "source_type": "fred_series",
            "source_url": "https://fred.stlouisfed.org/series/FEDFUNDS",
            "title": "FRED FEDFUNDS",
        }
    )

    assert grade["source_authority"] == "official_statistics"
    assert grade["authority_level"] == "primary"
    assert "macro_indicator" in grade["allowed_claim_types"]
    assert "revenue" not in grade["allowed_claim_types"]


def test_independent_bundle_skips_remote_sources_by_default():
    payload = fetch_independent_evidence_bundle(symbol="AAPL", period="2025Q4", enable_remote=False)

    assert payload["records"] == []
    assert payload["meta"]["failure_reason"] == "remote_sources_disabled"


def test_fred_series_fetch_normalizes_latest_observation(monkeypatch, tmp_path):
    monkeypatch.setenv("FRED_API_KEY", "fred-test")
    config_path = tmp_path / "data_sources.yaml"
    config_path.write_text(
        """
independent_sources:
  macro:
    fred:
      base_url: https://api.stlouisfed.org/fred/series/observations
      api_key_env: FRED_API_KEY
""".strip(),
        encoding="utf-8",
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"observations": [{"date": "2024-12-01", "value": "4.33"}]}).encode("utf-8")

    requested_urls = []

    def fake_urlopen(req, timeout):
        requested_urls.append(req.full_url)
        return FakeResponse()

    monkeypatch.setattr("src.data.independent_sources.request.urlopen", fake_urlopen)

    payload = fetch_fred_series_evidence(
        series={"FEDFUNDS": "Effective Federal Funds Rate"},
        config_path=str(config_path),
        period="FY2024",
    )

    assert payload.hits[0]["source_type"] == "fred_series"
    assert payload.hits[0]["data_cutoff"] == "2024-12-01"
    assert payload.hits[0]["authority_level"] == "primary"
    assert payload.hits[0]["metadata"]["target_period"] == "FY2024"
    assert payload.hits[0]["metadata"]["period_match"] is True
    assert "observation_end=2024-12-31" in requested_urls[0]
    assert payload.meta["failure_reason"] == ""


def test_bls_series_fetch_keeps_requested_report_period(monkeypatch, tmp_path):
    config_path = tmp_path / "data_sources.yaml"
    config_path.write_text("independent_sources:\n  macro:\n    bls: {}\n", encoding="utf-8")
    request_payloads = []

    def fake_post_json(url, payload, headers, timeout):
        request_payloads.append(payload)
        return {
            "Results": {
                "series": [
                    {
                        "seriesID": "LNS14000000",
                        "data": [{"year": "2024", "period": "M12", "value": "4.1"}],
                    }
                ]
            }
        }

    monkeypatch.setattr("src.data.independent_sources._post_json", fake_post_json)

    result = fetch_bls_series_evidence(
        series={"LNS14000000": "Unemployment Rate"},
        config_path=str(config_path),
        period="FY2024",
    )

    assert request_payloads[0]["startyear"] == "2024"
    assert request_payloads[0]["endyear"] == "2024"
    assert result.hits[0]["metadata"]["target_period"] == "FY2024"
    assert result.hits[0]["metadata"]["observation_date"] == "2024-M12"


def test_sec_companyfacts_fetch_normalizes_supported_metrics(monkeypatch, tmp_path):
    config_path = tmp_path / "data_sources.yaml"
    config_path.write_text(
        """
independent_sources:
  company:
    sec_edgar:
      companyfacts_base_url: https://data.sec.gov/api/xbrl/companyfacts
      cik_map:
        AAPL: "0000320193"
""".strip(),
        encoding="utf-8",
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "facts": {
                        "us-gaap": {
                            "Revenues": {
                                "units": {
                                    "USD": [
                                        {"val": 100, "end": "2025-12-31", "filed": "2026-01-30", "form": "10-K"}
                                    ]
                                }
                            }
                        }
                    }
                }
            ).encode("utf-8")

    monkeypatch.setattr("src.data.independent_sources.request.urlopen", lambda req, timeout: FakeResponse())

    payload = fetch_sec_companyfacts_evidence(symbol="AAPL", period="2025Q4", config_path=str(config_path))

    assert payload.hits[0]["source_type"] == "sec_companyfacts"
    assert payload.hits[0]["metadata"]["metrics"]["Revenues"]["value"] == 100
    assert payload.hits[0]["source_authority"] == "official"
    assert payload.meta["failure_reason"] == ""


def test_sec_companyfacts_fy_period_selects_fiscal_year_annual_record(monkeypatch, tmp_path):
    config_path = tmp_path / "data_sources.yaml"
    config_path.write_text(
        """
independent_sources:
  company:
    sec_edgar:
      companyfacts_base_url: https://data.sec.gov/api/xbrl/companyfacts
      cik_map:
        AAPL: "0000320193"
""".strip(),
        encoding="utf-8",
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            values = [
                {"val": 80, "end": "2023-09-30", "filed": "2024-11-01", "form": "10-K", "fy": 2024, "fp": "FY"},
                {"val": 90, "end": "2024-09-28", "filed": "2024-11-01", "form": "10-K", "fy": 2024, "fp": "FY"},
                {"val": 30, "end": "2024-12-28", "filed": "2025-01-31", "form": "10-Q", "fy": 2025, "fp": "Q1"},
            ]
            return json.dumps(
                {
                    "facts": {
                        "us-gaap": {
                            "Revenues": {"units": {"USD": values}},
                            "Liabilities": {"units": {"USD": [{**values[1], "val": 40}]}},
                            "StockholdersEquity": {"units": {"USD": [{**values[1], "val": 50}]}},
                            "NetCashProvidedByUsedInInvestingActivities": {
                                "units": {"USD": [{**values[1], "val": -12}]}
                            },
                            "NetCashProvidedByUsedInFinancingActivities": {
                                "units": {"USD": [{**values[1], "val": -8}]}
                            },
                        }
                    }
                }
            ).encode("utf-8")

    monkeypatch.setattr("src.data.independent_sources.request.urlopen", lambda req, timeout: FakeResponse())

    payload = fetch_sec_companyfacts_evidence(symbol="AAPL", period="FY2024", config_path=str(config_path))

    revenue = payload.hits[0]["metadata"]["metrics"]["Revenues"]
    assert revenue["value"] == 90
    assert revenue["end"] == "2024-09-28"
    assert revenue["fy"] == 2024
    assert revenue["fp"] == "FY"
    metrics = payload.hits[0]["metadata"]["metrics"]
    assert metrics["Liabilities"]["value"] == 40
    assert metrics["StockholdersEquity"]["value"] == 50
    assert metrics["NetCashProvidedByUsedInInvestingActivities"]["value"] == -12
    assert metrics["NetCashProvidedByUsedInFinancingActivities"]["value"] == -8
