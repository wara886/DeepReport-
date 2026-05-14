"""GapRouter maps structured verification gaps to targeted remediation owners."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List

from src.multiagent.gaps.schema import GapItem, GapStatus, GapType


ROUTE_TABLE: Dict[GapType, List[str]] = {
    GapType.EVIDENCE_GAP: ["ResearchAgent", "BrowserAgent"],
    GapType.NUMERIC_GAP: ["AnalyzeAgent"],
    GapType.VALUATION_GAP: ["ValuationAgent", "CompanyValuationModule"],
    GapType.CITATION_GAP: ["CitationManager", "ResearchAgent"],
    GapType.RISK_GAP: ["RiskAgent"],
    GapType.PEER_GAP: ["PeerComparisonAgent"],
    GapType.FORMAT_GAP: ["FinalWriterAgent"],
    GapType.COMPLIANCE_GAP: ["FinalWriterAgent", "ComplianceModule"],
    GapType.SYMBOL_PERIOD_MISMATCH: ["PlannerAgent", "ResearchAgent"],
    GapType.SOURCE_CONFLICT: ["FutureAdjudicator"],
}

ACTION_TABLE: Dict[GapType, str] = {
    GapType.EVIDENCE_GAP: "collect_or_refresh_supporting_evidence",
    GapType.NUMERIC_GAP: "recompute_or_reconcile_numeric_claims",
    GapType.VALUATION_GAP: "rerun_valuation_or_validate_assumptions",
    GapType.CITATION_GAP: "repair_claim_evidence_citation_alignment",
    GapType.RISK_GAP: "regenerate_or_expand_risk_analysis",
    GapType.PEER_GAP: "refresh_peer_selection_and_comparison",
    GapType.FORMAT_GAP: "revise_report_structure_or_format",
    GapType.COMPLIANCE_GAP: "add_or_fix_compliance_disclosure",
    GapType.SYMBOL_PERIOD_MISMATCH: "replan_with_correct_entity_or_period",
    GapType.SOURCE_CONFLICT: "future_adjudicator_conflict_resolution",
}


@dataclass(frozen=True)
class GapRoute:
    gap_id: str
    gap_type: str
    routed_to: List[str]
    action: str
    status: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gap_id": self.gap_id,
            "gap_type": self.gap_type,
            "routed_to": list(self.routed_to),
            "action": self.action,
            "status": self.status,
        }


class GapRouter:
    def route(self, gap: GapItem | Dict[str, Any]) -> GapRoute:
        item = gap if isinstance(gap, GapItem) else GapItem.from_dict(dict(gap))
        agents = route_agents_for_gap_type(item.gap_type)
        return GapRoute(
            gap_id=item.gap_id,
            gap_type=item.gap_type.value,
            routed_to=agents,
            action=ACTION_TABLE[item.gap_type],
            status=GapStatus.ROUTED.value,
        )

    def route_many(self, gaps: Iterable[GapItem | Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [self.route(gap).to_dict() for gap in gaps]

    def apply_routes(self, gaps: Iterable[GapItem | Dict[str, Any]]) -> List[GapItem]:
        routed: List[GapItem] = []
        for gap in gaps:
            item = gap if isinstance(gap, GapItem) else GapItem.from_dict(dict(gap))
            routed.append(item.with_route(route_agents_for_gap_type(item.gap_type)))
        return routed


def route_agents_for_gap_type(gap_type: GapType) -> List[str]:
    return list(ROUTE_TABLE.get(gap_type, ["FinalWriterAgent"]))


def route_action_for_gap_type(gap_type: GapType) -> str:
    return ACTION_TABLE.get(gap_type, "revise_report")
