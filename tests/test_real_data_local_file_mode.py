from pathlib import Path

import pytest

from src.app.stage11a_real_data_pipeline import run_real_data_pipeline
from src.data.fetch_market import MarketFetcher
from src.data.manifest import build_manifest


def test_local_real_path_reading():
    fetcher = MarketFetcher(
        mode="local_file_real",
        real_data_root="data/raw/real_data",
        symbol="AAPL",
        period="2025Q4",
        real_file_path="data/raw/real_data/AAPL/2025Q4/market.csv",
    )
    rows = fetcher.fetch()
    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL"


def test_required_field_validation_raises(tmp_path: Path):
    root = tmp_path / "real_data" / "AAPL" / "2025Q4"
    root.mkdir(parents=True, exist_ok=True)
    # Missing source_url on purpose.
    (root / "market.csv").write_text(
        "symbol,period,publish_time,close,volume,trust_level\n"
        "AAPL,2025Q4,2026-01-31,212.35,100,high\n",
        encoding="utf-8",
    )

    fetcher = MarketFetcher(
        mode="local_file_real",
        real_data_root=str(tmp_path / "real_data"),
        symbol="AAPL",
        period="2025Q4",
        real_file_path=str(root / "market.csv"),
    )
    rows = fetcher.fetch()
    with pytest.raises(ValueError):
        build_manifest(rows, source_type="market", strict_required=True)


def test_stage11a_parquet_and_report_export():
    outputs = run_real_data_pipeline("configs/local_real_smoke.yaml")

    assert Path("data/curated_real/real_data_manifest.parquet").exists()
    assert Path("data/curated_real/real_data_manifest.json").exists()
    assert Path("data/features_real/feature_report_real.json").exists()
    assert Path(outputs["report_md"]).exists()
    assert Path(outputs["report_html"]).exists()
    assert Path(outputs["report_json"]).exists()

