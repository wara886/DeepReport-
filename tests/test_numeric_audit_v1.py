from src.evaluation.numeric_audit import run_numeric_audit_for_case, summarize_numeric_audit


def test_numeric_audit_v1_support_and_mismatch():
    case = {
        "case_id": "ev1_case_001",
        "period": "2025Q4",
        "gold_numeric_facts": [
            {"metric": "revenue", "value": "126.3", "unit": "billion", "period": "2025Q4"},
            {"metric": "gross_margin", "value": "46.8", "unit": "pct", "period": "2025Q4"},
            {"metric": "yoy", "value": "11.2", "unit": "pct", "period": "2025Q4"},
            {"metric": "net_income", "value": "31.1", "unit": "billion", "period": "2025Q4"},
        ],
    }
    claims = [
        {
            "claim_id": "cl1",
            "claim_text": "Revenue was 126.3B.",
            "numeric_values": {"revenue_billion": 126.3},
            "evidence_ids": ["a"],
        },
        {
            "claim_id": "cl2",
            "claim_text": "Gross margin was 40.0%.",
            "numeric_values": {"gross_margin_pct": 40.0},
            "evidence_ids": ["b"],
        },
    ]
    result = run_numeric_audit_for_case(case=case, report_claims=claims, abs_tol=0.1, rel_tol=0.001)
    assert result["numeric_claims"] == 2
    assert result["supported_numeric_claims"] == 1
    assert result["error_breakdown"]["value_mismatch"] == 1


def test_numeric_audit_v1_summary():
    summary = summarize_numeric_audit(
        [
            {
                "numeric_claims": 2,
                "supported_numeric_claims": 1,
                "unsupported_numeric_claims": 1,
                "error_breakdown": {
                    "value_mismatch": 1,
                    "unit_mismatch": 0,
                    "period_mismatch": 0,
                    "unsupported_number": 0,
                    "hallucinated_number": 0,
                },
            }
        ]
    )
    assert summary["case_count"] == 1
    assert summary["numeric_accuracy"] == 0.5

