import json

from scripts.run_realtime_data_smoke import main


def test_realtime_data_smoke_skips_remote_sources_without_flag(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    code = main(["--output-dir", str(tmp_path / "smoke"), "--symbol", "AAPL", "--period", "2025Q4"])

    summary = json.loads((tmp_path / "smoke" / "realtime_data_smoke_summary.json").read_text(encoding="utf-8"))
    assert code == 0
    assert summary["remote_data_enabled"] is False
    assert summary["independent_record_count"] == 0
    assert summary["deepseek"]["status"] == "skipped"
    assert (tmp_path / "smoke" / "industry_report.docx").exists()
    assert (tmp_path / "smoke" / "macro_report.docx").exists()
