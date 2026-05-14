import json
from pathlib import Path

import pytest

from src.eval.schema import case_json_schema, load_eval_cases, validate_eval_case, write_eval_cases_jsonl


def _case():
    return {
        "case_id": "case_001",
        "symbol": "aapl",
        "market": "US",
        "period": "2025Q4",
        "topic": "基本面、估值、风险",
        "report_type": "company_research",
        "required_sections": ["business_overview", "financials", "valuation"],
        "required_source_types": ["financials", "filing"],
        "difficulty": "normal",
        "tags": ["phase0"],
    }


def test_validate_eval_case_normalizes_symbol_and_keeps_required_fields():
    case = validate_eval_case(_case())

    assert case.case_id == "case_001"
    assert case.symbol == "AAPL"
    assert case.market == "US"
    assert case.required_sections == ["business_overview", "financials", "valuation"]
    assert "AAPL" in case.query


def test_validate_eval_case_rejects_missing_required_list():
    row = _case()
    row["required_sections"] = []

    with pytest.raises(ValueError, match="required_sections"):
        validate_eval_case(row)


def test_validate_eval_case_rejects_unknown_difficulty():
    row = _case()
    row["difficulty"] = "extreme"

    with pytest.raises(ValueError, match="difficulty"):
        validate_eval_case(row)


def test_load_eval_cases_reads_directory_json_and_jsonl(tmp_path: Path):
    json_path = tmp_path / "one.json"
    jsonl_path = tmp_path / "many.jsonl"
    json_path.write_text(json.dumps(_case(), ensure_ascii=False), encoding="utf-8")
    second = _case()
    second["case_id"] = "case_002"
    write_eval_cases_jsonl(jsonl_path, [second])

    cases = load_eval_cases(tmp_path)

    assert [case.case_id for case in cases] == ["case_001", "case_002"]


def test_case_json_schema_contains_phase0_required_fields():
    schema = case_json_schema()

    assert "case_id" in schema["required"]
    assert "market" in schema["required"]
    assert "required_source_types" in schema["required"]
    assert schema["properties"]["difficulty"]["enum"] == ["easy", "hard", "normal"]
