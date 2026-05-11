from src.agents.context_packer import pack_claims, pack_evidence_records


def test_pack_evidence_prioritizes_cited_records_and_reports_dropped_ids():
    records = [
        {
            "evidence_id": "ev_low",
            "content": "low priority " * 30,
            "trust_level": "high",
            "score": 99,
            "metadata": {"supported_claim_count": 0},
        },
        {
            "evidence_id": "ev_cited",
            "content": "cited evidence " * 30,
            "trust_level": "low",
            "score": 1,
            "metadata": {"supported_claim_count": 1},
        },
        {
            "evidence_id": "ev_extra",
            "content": "extra evidence " * 30,
            "trust_level": "medium",
            "score": 50,
            "metadata": {"supported_claim_count": 0},
        },
    ]

    packed, meta = pack_evidence_records(
        records,
        prioritized_evidence_ids=["ev_cited"],
        max_items=1,
        content_limit=80,
        total_chars=900,
    )

    assert [item["evidence_id"] for item in packed] == ["ev_cited"]
    assert meta["dropped_count"] == 2
    assert "ev_low" in meta["dropped_ids"]
    assert meta["prioritized_dropped_ids"] == []


def test_pack_claims_reports_context_budget_trace():
    claims = [
        {
            "claim_id": f"cl_{idx}",
            "section_name": "financial_analysis",
            "claim_text": "Revenue claim " * 20,
            "evidence_ids": [f"ev_{idx}"],
            "numeric_values": {"revenue_billion": float(idx)},
            "confidence": 0.9 - idx * 0.1,
        }
        for idx in range(4)
    ]

    packed, meta = pack_claims(claims, max_items=2, text_limit=80, total_chars=2000)

    assert len(packed) == 2
    assert meta["input_count"] == 4
    assert meta["packed_count"] == 2
    assert meta["dropped_count"] == 2
    assert meta["packed_ids"] == ["cl_0", "cl_1"]
    assert meta["dropped_ids"] == ["cl_2", "cl_3"]
