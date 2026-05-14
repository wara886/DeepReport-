from pathlib import Path

from src.agents.base_agent import AgentTask
from src.agents.multi_agent_orchestrator import build_rework_trace
from src.agents.verifier_agent import VerifierAgent
from src.eval.metrics import gap_detection_count, gap_resolution_rate
from src.multiagent.gaps.detector import gaps_from_verification_report, infer_gap_type
from src.multiagent.gaps.router import GapRouter
from src.multiagent.gaps.schema import GapItem, GapSeverity, GapType
from src.schemas.claim import ClaimItem


def _gap(gap_type: GapType) -> GapItem:
    return GapItem(
        gap_id=f"gap_{gap_type.value.lower()}",
        gap_type=gap_type,
        severity=GapSeverity.HIGH,
        detected_by="VerifierAgent",
        description="test gap",
        recommended_action="test action",
    )


def test_gap_router_routes_at_least_five_gap_types():
    router = GapRouter()

    assert router.route(_gap(GapType.EVIDENCE_GAP)).routed_to == ["ResearchAgent", "BrowserAgent"]
    assert router.route(_gap(GapType.NUMERIC_GAP)).routed_to == ["AnalyzeAgent"]
    assert router.route(_gap(GapType.VALUATION_GAP)).routed_to == ["ValuationAgent", "CompanyValuationModule"]
    assert router.route(_gap(GapType.CITATION_GAP)).routed_to == ["CitationManager", "ResearchAgent"]
    assert router.route(_gap(GapType.RISK_GAP)).routed_to == ["RiskAgent"]
    assert router.route(_gap(GapType.PEER_GAP)).routed_to == ["PeerComparisonAgent"]


def test_source_conflict_routes_to_future_adjudicator():
    route = GapRouter().route(_gap(GapType.SOURCE_CONFLICT))

    assert route.routed_to == ["FutureAdjudicator"]
    assert route.action == "future_adjudicator_conflict_resolution"


def test_gap_detector_maps_verifier_messages_to_canonical_gaps():
    report = {
        "errors": [
            "Claim cl_1 references missing evidence ids: ev_missing",
            "Valuation reproducibility check failed.",
            "Target symbol mismatch: expected NVDA, but evidence symbols are AAPL.",
            "Missing required header in report: ## Risk Assessment",
        ],
        "warnings": ["Claim cl_2 numeric value revenue=123 was not found in linked evidence."],
    }

    gaps = gaps_from_verification_report(report, claims=[{"claim_id": "cl_1", "section_name": "financial_analysis"}])
    gap_types = {gap["gap_type"] for gap in gaps}

    assert GapType.EVIDENCE_GAP.value in gap_types
    assert GapType.VALUATION_GAP.value in gap_types
    assert GapType.SYMBOL_PERIOD_MISMATCH.value in gap_types
    assert GapType.FORMAT_GAP.value in gap_types
    assert GapType.NUMERIC_GAP.value in gap_types
    assert all(gap["status"] == "routed" for gap in gaps)


def test_verifier_output_keeps_legacy_fields_and_adds_structured_gaps():
    claim = ClaimItem(
        claim_id="cl_1",
        section_name="financial_analysis",
        claim_text="NVDA revenue was 10B.",
        evidence_ids=["ev_missing"],
        numeric_values={"revenue_billion": 10.0},
        risk_level="medium",
        confidence=0.9,
    )
    result = VerifierAgent(model=None).execute_task(
        AgentTask(
            task_id="verify",
            task_type="verifier",
            description="verify",
            parameters={
                "claims": [claim.to_dict()],
                "markdown": "# Report\n\n## Executive Summary\n\n## Financial Analysis\n\n## Risk Assessment\n\nNVDA revenue was 10B.",
                "evidence_records": [],
                "expected_symbol": "NVDA",
                "period": "2025Q4",
            },
        )
    )

    report = result.output["verification_report"]
    assert "errors" in report
    assert "warnings" in report
    assert "evidence_gaps" in report
    assert "gaps" in report
    assert report["gap_count"] == len(report["gaps"])
    assert any(gap["gap_type"] in {GapType.EVIDENCE_GAP.value, GapType.CITATION_GAP.value} for gap in report["gaps"])


def test_rework_trace_records_route_and_resolution_state():
    gaps = [
        _gap(GapType.EVIDENCE_GAP).to_dict(),
        _gap(GapType.SOURCE_CONFLICT).to_dict(),
    ]

    trace = build_rework_trace(gaps, gap_resolution_trace=[])

    assert trace[0]["gap_id"] == "gap_evidence_gap"
    assert trace[0]["routed_to"] == ["ResearchAgent", "BrowserAgent"]
    assert trace[0]["resolved"] is False
    assert trace[1]["routed_to"] == ["FutureAdjudicator"]


def test_gap_eval_metrics_count_and_resolution_rate():
    verification = {"gaps": [_gap(GapType.EVIDENCE_GAP).to_dict(), _gap(GapType.NUMERIC_GAP).to_dict()]}
    rework_trace = [{"resolved": True}, {"resolved": False}]

    assert gap_detection_count(verification) == 2
    assert gap_resolution_rate(rework_trace) == 0.5
