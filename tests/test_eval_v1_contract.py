from pathlib import Path

from src.evaluation.eval_v1 import (
    audit_eval_v1_cases,
    load_eval_cases,
    seed_eval_v1_cases,
    validate_eval_case,
    write_eval_cases,
    write_eval_schema,
)


def test_eval_v1_validate_case_minimal():
    payload = {
        "case_id": "ev1_demo_001",
        "query": "analyze demo",
        "task_type": "financial",
        "source_scope": ["financials", "filing"],
        "gold_claims": ["Revenue claim must be supported."],
        "gold_evidence_ids": ["demo:financials"],
        "gold_numeric_facts": [
            {"metric": "revenue", "value": "100.0", "unit": "billion", "period": "2025Q4"},
        ],
        "allow_fallback": False,
        "symbol": "DEMO",
        "period": "2025Q4",
    }
    case = validate_eval_case(payload)
    assert case.case_id == "ev1_demo_001"
    assert case.task_type == "financial"


def test_eval_v1_seed_and_roundtrip(tmp_path: Path):
    raw_root = tmp_path / "raw"
    (raw_root / "AAA" / "2025Q4").mkdir(parents=True)
    (raw_root / "BBB" / "2025Q4").mkdir(parents=True)
    cases = seed_eval_v1_cases(raw_root=raw_root, min_case_count=30)
    assert len(cases) == 30

    out_dir = tmp_path / "eval_v1"
    write_eval_cases(out_dir / "cases.jsonl", cases)
    write_eval_schema(out_dir / "schema.json")
    loaded = load_eval_cases(out_dir / "cases.jsonl")
    assert len(loaded) == 30
    assert (out_dir / "schema.json").exists()
    assert "should be evidence-grounded" not in loaded[0].gold_claims[0]


def test_eval_v1_audit_detects_quality_issues(tmp_path: Path):
    payload = {
        "case_id": "ev1_demo_001",
        "query": "analyze demo",
        "task_type": "financial",
        "source_scope": ["financials", "filing"],
        "gold_claims": ["Revenue claim should be evidence-grounded."],
        "gold_evidence_ids": ["demo:financials"],
        "gold_numeric_facts": [
            {"metric": "revenue", "value": "unknown", "unit": "billion", "period": "2025Q4"},
        ],
        "allow_fallback": False,
        "symbol": "DEMO",
        "period": "2025Q4",
    }
    case = validate_eval_case(payload)

    audit = audit_eval_v1_cases([case], raw_root=tmp_path / "raw")

    assert audit["passed"] is False
    assert audit["issues"]["placeholder_claim_cases"] == ["ev1_demo_001"]
    assert audit["issues"]["unknown_numeric_cases"] == ["ev1_demo_001"]
    assert audit["issues"]["missing_source_cases"][0]["missing_sources"] == ["financials", "filing"]
