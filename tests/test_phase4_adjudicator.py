"""Tests for Phase 4: AdjudicatorAgent and SOURCE_CONFLICT routing."""

from __future__ import annotations

from src.agents.adjudicator_agent import (
    AdjudicatorAgent,
    KEEP_FIRST,
    KEEP_SECOND,
    MERGE,
    UNCERTAIN,
    _adjudicate_claims,
    _adjudicate_evidence,
)
from src.agents.base_agent import AgentStatus, AgentTask, TaskResult
from src.agents.multi_agent_orchestrator import merge_task_result
from src.eval.metrics import compute_case_metrics
from src.eval.schema import EvalCase
from src.multiagent.gaps.detector import gaps_from_verification_report, infer_gap_type
from src.multiagent.gaps.schema import GapType
from src.multiagent.router import DynamicRouter, RouterInput


# ─── AdjudicatorAgent 基础测试 ──────────────────────────────────────────────

def _task(gap_id="g1", conflicting_claims=None, conflicting_evidence=None):
    return AgentTask(
        task_id="t1",
        task_type="adjudicator",
        description="test adjudication",
        parameters={
            "gap_id": gap_id,
            "gap_description": "conflicting revenue figures",
            "conflicting_claims": conflicting_claims or [],
            "conflicting_evidence": conflicting_evidence or [],
            "symbol": "NVDA",
        },
    )


def test_adjudicator_returns_completed_status():
    agent = AdjudicatorAgent()
    result = agent.execute_task(_task())
    assert result.status == AgentStatus.COMPLETED


def test_adjudicator_no_conflicts_returns_uncertain():
    agent = AdjudicatorAgent()
    result = agent.execute_task(_task())
    decisions = result.output["adjudication_decisions"]
    assert len(decisions) == 1
    assert decisions[0]["decision"] == UNCERTAIN
    assert decisions[0]["conflict_type"] == "unknown"


def test_adjudicator_claim_higher_trust_wins():
    claims = [
        {"claim_id": "cl_a", "trust_level": "high", "source_type": "filing"},
        {"claim_id": "cl_b", "trust_level": "low", "source_type": "news"},
    ]
    agent = AdjudicatorAgent()
    result = agent.execute_task(_task(conflicting_claims=claims))
    decisions = result.output["adjudication_decisions"]
    claim_decisions = [d for d in decisions if d["conflict_type"] == "claim"]
    assert len(claim_decisions) == 1
    assert claim_decisions[0]["decision"] == KEEP_FIRST
    assert claim_decisions[0]["kept_claim_id"] == "cl_a"


def test_adjudicator_claim_second_higher_trust():
    claims = [
        {"claim_id": "cl_a", "trust_level": "low", "source_type": "news"},
        {"claim_id": "cl_b", "trust_level": "high", "source_type": "filing"},
    ]
    agent = AdjudicatorAgent()
    result = agent.execute_task(_task(conflicting_claims=claims))
    decisions = result.output["adjudication_decisions"]
    claim_decisions = [d for d in decisions if d["conflict_type"] == "claim"]
    assert claim_decisions[0]["decision"] == KEEP_SECOND
    assert claim_decisions[0]["kept_claim_id"] == "cl_b"


def test_adjudicator_equal_trust_returns_uncertain():
    claims = [
        {"claim_id": "cl_a", "trust_level": "medium", "source_type": "news"},
        {"claim_id": "cl_b", "trust_level": "medium", "source_type": "news"},
    ]
    agent = AdjudicatorAgent()
    result = agent.execute_task(_task(conflicting_claims=claims))
    decisions = result.output["adjudication_decisions"]
    claim_decisions = [d for d in decisions if d["conflict_type"] == "claim"]
    assert claim_decisions[0]["decision"] == UNCERTAIN


def test_adjudicator_numeric_within_5pct_merges():
    claims = [
        {"claim_id": "cl_a", "trust_level": "high", "source_type": "filing",
         "numeric_values": {"revenue_billion": 22.0}},
        {"claim_id": "cl_b", "trust_level": "medium", "source_type": "news",
         "numeric_values": {"revenue_billion": 22.5}},
    ]
    agent = AdjudicatorAgent()
    result = agent.execute_task(_task(conflicting_claims=claims))
    decisions = result.output["adjudication_decisions"]
    claim_decisions = [d for d in decisions if d["conflict_type"] == "claim"]
    assert claim_decisions[0]["decision"] == MERGE
    assert claim_decisions[0]["confidence"] >= 0.8


def test_adjudicator_numeric_beyond_5pct_uses_trust():
    claims = [
        {"claim_id": "cl_a", "trust_level": "high", "source_type": "filing",
         "numeric_values": {"revenue_billion": 22.0}},
        {"claim_id": "cl_b", "trust_level": "low", "source_type": "news",
         "numeric_values": {"revenue_billion": 25.0}},  # >5% diff
    ]
    agent = AdjudicatorAgent()
    result = agent.execute_task(_task(conflicting_claims=claims))
    decisions = result.output["adjudication_decisions"]
    claim_decisions = [d for d in decisions if d["conflict_type"] == "claim"]
    assert claim_decisions[0]["decision"] == KEEP_FIRST  # cl_a has higher trust


def test_adjudicator_evidence_higher_trust_wins():
    evidence = [
        {"evidence_id": "ev_a", "trust_level": "high", "source_type": "sec_filing"},
        {"evidence_id": "ev_b", "trust_level": "low", "source_type": "web"},
    ]
    agent = AdjudicatorAgent()
    result = agent.execute_task(_task(conflicting_evidence=evidence))
    decisions = result.output["adjudication_decisions"]
    ev_decisions = [d for d in decisions if d["conflict_type"] == "evidence"]
    assert len(ev_decisions) == 1
    assert ev_decisions[0]["decision"] == KEEP_FIRST
    assert ev_decisions[0]["kept_evidence_id"] == "ev_a"


def test_adjudicator_output_has_resolved_count():
    claims = [
        {"claim_id": "cl_a", "trust_level": "high", "source_type": "filing"},
        {"claim_id": "cl_b", "trust_level": "low", "source_type": "news"},
    ]
    agent = AdjudicatorAgent()
    result = agent.execute_task(_task(conflicting_claims=claims))
    assert result.output["resolved_count"] == 1
    assert result.output["uncertain_count"] == 0


def test_adjudicator_output_has_gap_id():
    agent = AdjudicatorAgent()
    result = agent.execute_task(_task(gap_id="gap_conflict_001"))
    assert result.output["gap_id"] == "gap_conflict_001"


# ─── 裁决规则单元测试 ────────────────────────────────────────────────────────

def test_adjudicate_claims_filing_beats_news():
    result = _adjudicate_claims(
        {"claim_id": "a", "trust_level": "medium", "source_type": "sec_filing"},
        {"claim_id": "b", "trust_level": "medium", "source_type": "news"},
        symbol="NVDA",
    )
    assert result["verdict"] == KEEP_FIRST  # filing gets +1 bonus


def test_adjudicate_evidence_filing_beats_web():
    result = _adjudicate_evidence(
        {"evidence_id": "a", "trust_level": "medium", "source_type": "10-k"},
        {"evidence_id": "b", "trust_level": "medium", "source_type": "web"},
    )
    assert result["verdict"] == KEEP_FIRST


def test_adjudicate_claims_confidence_range():
    result = _adjudicate_claims(
        {"claim_id": "a", "trust_level": "high"},
        {"claim_id": "b", "trust_level": "low"},
        symbol="NVDA",
    )
    assert 0.0 <= result["confidence"] <= 1.0


def test_source_conflict_detector_preserves_structured_conflict_context():
    report = {
        "errors": ["Source conflict between revenue claims: ev_filing, ev_news"],
        "evidence_gaps": [
            {
                "gap_id": "gap_source_conflict_001",
                "gap_type": "source_conflict",
                "description": "Source conflict between revenue claims.",
                "conflicting_claims": [
                    {"claim_id": "cl_a", "trust_level": "high", "source_type": "filing"},
                    {"claim_id": "cl_b", "trust_level": "low", "source_type": "news"},
                ],
                "conflicting_evidence": [
                    {"evidence_id": "ev_filing", "trust_level": "high", "source_type": "10-q"},
                    {"evidence_id": "ev_news", "trust_level": "low", "source_type": "web"},
                ],
            }
        ],
    }

    gaps = gaps_from_verification_report(report)
    source_conflicts = [gap for gap in gaps if gap["gap_type"] == GapType.SOURCE_CONFLICT.value]

    assert source_conflicts
    assert source_conflicts[0]["conflicting_claims"][0]["claim_id"] == "cl_a"
    assert source_conflicts[0]["conflicting_evidence"][1]["evidence_id"] == "ev_news"


def test_source_conflict_detector_can_hydrate_context_from_related_ids():
    report = {"errors": ["Source conflict between evidence ids: ev_filing, ev_news"]}
    evidence = [
        {"evidence_id": "ev_filing", "trust_level": "high", "source_type": "10-q"},
        {"evidence_id": "ev_news", "trust_level": "low", "source_type": "web"},
    ]

    gaps = gaps_from_verification_report(report, evidence_records=evidence)
    source_conflict = next(gap for gap in gaps if gap["gap_type"] == GapType.SOURCE_CONFLICT.value)

    assert [item["evidence_id"] for item in source_conflict["conflicting_evidence"]] == ["ev_filing", "ev_news"]


def test_infer_gap_type_detects_source_conflict():
    assert infer_gap_type("Inconsistent source values found for revenue") == GapType.SOURCE_CONFLICT


def test_merge_task_result_accumulates_adjudication_decisions():
    state = {}
    result = TaskResult(
        task_id="task_adj",
        agent_name="AdjudicatorAgent",
        status=AgentStatus.COMPLETED,
        output={"adjudication_decisions": [{"gap_id": "g1", "decision": KEEP_FIRST}]},
    )

    merge_task_result(state, "adjudicator", result)

    assert state["adjudication_decisions"] == [{"gap_id": "g1", "decision": KEEP_FIRST}]


def test_eval_metrics_counts_uncertain_adjudications_from_summary():
    case = EvalCase(
        case_id="case_1",
        symbol="NVDA",
        market="US",
        period="latest_quarter",
        topic="test",
        report_type="company_research",
        required_sections=[],
        required_source_types=[],
        difficulty="normal",
    )

    metrics = compute_case_metrics(
        case,
        {
            "markdown": "report",
            "claims": [],
            "evidence": [],
            "citations": [],
            "verification": {"passed": True, "gaps": []},
            "run_summary": {
                "adjudication_decisions": [
                    {"gap_id": "g1", "decision": UNCERTAIN},
                    {"gap_id": "g2", "decision": KEEP_FIRST},
                ]
            },
            "artifacts": {},
        },
    )

    assert metrics["conflict_resolution_count"] == 1
    assert metrics["adjudication_decision_distribution"] == {UNCERTAIN: 1, KEEP_FIRST: 1}



def _router_input_with_gap(gap_type: str, gap_id: str = "g1") -> RouterInput:
    return RouterInput(
        open_gaps=[{"gap_id": gap_id, "gap_type": gap_type, "severity": "high", "status": "open"}],
    )


def test_dynamic_router_source_conflict_routes_to_adjudicator():
    router = DynamicRouter()
    decisions = router.decide(_router_input_with_gap("SOURCE_CONFLICT"))
    executes = [d for d in decisions if d.selected_action == "execute"]
    assert len(executes) == 1
    assert executes[0].selected_agent == "adjudicator"
    assert executes[0].selected_task_type == "adjudicator"
    assert executes[0].fallback_used is False


def test_dynamic_router_source_conflict_expected_effect():
    router = DynamicRouter()
    decisions = router.decide(_router_input_with_gap("SOURCE_CONFLICT"))
    executes = [d for d in decisions if d.selected_action == "execute"]
    assert executes[0].expected_effect == "adjudicate_conflicting_claims_or_evidence"


def test_dynamic_router_valuation_gap_still_fallback():
    """VALUATION_GAP 仍然是 unsupported，不应路由到 adjudicator。"""
    router = DynamicRouter()
    decisions = router.decide(_router_input_with_gap("VALUATION_GAP"))
    fallbacks = [d for d in decisions if d.selected_action == "fallback"]
    assert len(fallbacks) == 1
    assert fallbacks[0].unsupported_gap_type == "VALUATION_GAP"


def test_dynamic_router_compliance_gap_still_fallback():
    router = DynamicRouter()
    decisions = router.decide(_router_input_with_gap("COMPLIANCE_GAP"))
    fallbacks = [d for d in decisions if d.selected_action == "fallback"]
    assert len(fallbacks) == 1


def test_dynamic_router_symbol_period_mismatch_still_fallback():
    router = DynamicRouter()
    decisions = router.decide(_router_input_with_gap("SYMBOL_PERIOD_MISMATCH"))
    fallbacks = [d for d in decisions if d.selected_action == "fallback"]
    assert len(fallbacks) == 1
