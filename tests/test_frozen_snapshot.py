import json

from src.evaluation.frozen_snapshot import build_frozen_snapshot, load_snapshot_case_evidence, validate_frozen_snapshot


def test_snapshot_builder_records_missing_cases_and_validates_hashes(tmp_path):
    config = _write_config(tmp_path)
    source = tmp_path / "sources" / "case_a"
    source.mkdir(parents=True)
    source.joinpath("evidence.jsonl").write_text(json.dumps(_evidence("AAPL")) + "\n", encoding="utf-8")

    manifest = build_frozen_snapshot(config, source_root=tmp_path / "sources", snapshot_root=tmp_path / "snapshot")
    validation = validate_frozen_snapshot(tmp_path / "snapshot", require_complete=False)

    assert manifest["ready_case_count"] == 1
    assert manifest["complete"] is False
    assert manifest["snapshot_sha256"]
    assert manifest["missing_or_invalid_cases"] == ["case_b"]
    assert validation["valid"] is True
    assert load_snapshot_case_evidence(tmp_path / "snapshot", "case_a")[0]["period"] == "FY2024"


def test_snapshot_hash_mismatch_is_rejected(tmp_path):
    config = _write_config(tmp_path, cases=[("case_a", "AAPL")])
    source = tmp_path / "sources" / "case_a"
    source.mkdir(parents=True)
    source.joinpath("evidence.jsonl").write_text(json.dumps(_evidence("AAPL")) + "\n", encoding="utf-8")
    build_frozen_snapshot(config, source_root=tmp_path / "sources", snapshot_root=tmp_path / "snapshot")
    frozen = tmp_path / "snapshot" / "cases" / "case_a" / "evidence.jsonl"
    frozen.write_text(frozen.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")

    result = validate_frozen_snapshot(tmp_path / "snapshot", require_complete=True)

    assert result["valid"] is False
    assert "sha256 mismatch" in result["validation_issues"][0]


def _write_config(tmp_path, cases=None):
    cases = cases or [("case_a", "AAPL"), ("case_b", "MSFT")]
    path = tmp_path / "formal.yaml"
    case_lines = "\n".join(
        f"    - {{case_id: {case_id}, market: US, company_name: Name, canonical_symbol: {symbol}}}"
        for case_id, symbol in cases
    )
    path.write_text(
        f"""
benchmark:
  id: test_formal
  period: FY2024
  dataset_version: test_v1
  variants:
    - {{id: direct_llm}}
    - {{id: single_agent_rag}}
    - {{id: multi_agent_rag}}
  cases:
{case_lines}
""".strip(),
        encoding="utf-8",
    )
    return path


def _evidence(symbol):
    return {
        "evidence_id": "ev_annual",
        "source_type": "financials",
        "title": f"{symbol} FY2024 annual filing revenue",
        "source_url": "https://example.com/annual",
        "publish_time": "2025-03-01",
        "content": f"{symbol} FY2024 revenue was 100.0. Profit and cash flow were disclosed.",
        "symbol": symbol,
        "period": "FY2024",
        "trust_level": "high",
    }
