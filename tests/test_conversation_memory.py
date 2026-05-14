from src.agents.conversation_memory import (
    absorb_verifier_feedback,
    build_initial_conversation_state,
    conversation_state_from_dict,
)


def test_conversation_memory_preserves_scope_constraints_and_pinned_facts():
    state = build_initial_conversation_state(
        research_topic="Analyze AAPL 2025Q4",
        requirements=["All claims need evidence_id.", "Do not invent numbers."],
        symbol="AAPL",
        period="2025Q4",
    )

    brief = state.context_brief()

    assert "Analyze AAPL 2025Q4" in brief
    assert "symbol=AAPL" in brief
    assert "period=2025Q4" in brief
    assert "evidence_id" in brief
    assert "Do not invent numbers" in brief
    assert "scope_memory" in brief
    assert "domain_memory" in brief


def test_conversation_memory_absorbs_verifier_feedback_and_rejected_claims():
    state = build_initial_conversation_state(
        research_topic="Analyze AAPL 2025Q4",
        requirements=[],
        symbol="AAPL",
        period="2025Q4",
    )
    run_state = {"conversation_context": state.to_dict(), "verification_report": {
        "errors": ["Missing evidence citation for revenue claim."],
        "fix_recommendations": ["Add [ev_fin] to the revenue sentence."],
        "revision_brief": "- Errors: Missing evidence citation for revenue claim.",
    }}

    brief = absorb_verifier_feedback(run_state)
    restored = conversation_state_from_dict(run_state["conversation_context"])

    assert "Missing evidence citation" in brief
    assert restored is not None
    assert restored.rejected_claims
    assert run_state["conversation_brief"] == brief


def test_conversation_memory_context_brief_is_bounded():
    state = build_initial_conversation_state(
        research_topic="Analyze AAPL 2025Q4",
        requirements=[f"Requirement {index} " + "x" * 80 for index in range(30)],
        symbol="AAPL",
        period="2025Q4",
    )

    brief = state.context_brief(max_chars=500)

    assert len(brief) <= 500
    assert brief.endswith("...[compressed]")


def test_conversation_memory_builds_layered_run_state_memory():
    state = build_initial_conversation_state(
        research_topic="Analyze META latest",
        requirements=[],
        symbol="META",
        period="latest",
    )
    run_state = {
        "conversation_context": state.to_dict(),
        "symbol": "META",
        "period": "latest",
        "evidence_records": [
            {"evidence_id": "ev_fin", "source_type": "financials", "metadata": {"symbol": "META"}},
            {"evidence_id": "ev_mkt", "source_type": "market_api"},
        ],
        "claims": [
            {
                "claim_id": "cl_peer",
                "section_name": "peer_compare",
                "claim_text": "Peer claim",
                "evidence_ids": ["ev_fin"],
                "numeric_values": {"free_cash_flow_billion": 12.4},
            }
        ],
        "analysis_artifacts": {"financial_metrics": {"metric_count": 3}},
    }

    restored = conversation_state_from_dict(run_state["conversation_context"])
    assert restored is not None
    restored.absorb_run_state(run_state)
    payload = restored.to_dict()

    assert payload["working_memory"]["evidence_count"] == 2
    assert payload["evidence_memory"]["market_snapshot_ids"] == ["ev_mkt"]
    assert any("FCF wording" in item for item in payload["domain_memory"]["rules"])
