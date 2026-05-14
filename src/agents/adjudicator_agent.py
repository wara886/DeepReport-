"""AdjudicatorAgent: resolves SOURCE_CONFLICT gaps by adjudicating between conflicting claims or evidence."""

from __future__ import annotations

from typing import Any, Dict, List

from src.agents.base_agent import AgentStatus, AgentTask, BaseAgent, TaskResult


# Adjudication decision types
KEEP_FIRST = "keep_first"
KEEP_SECOND = "keep_second"
MERGE = "merge"
UNCERTAIN = "uncertain"


class AdjudicatorAgent(BaseAgent):
    """Resolves SOURCE_CONFLICT gaps by comparing conflicting claims/evidence and producing a verdict.

    Decision logic (rule-based, no LLM required):
    - If one source has higher trust_level → keep that one
    - If one source is a filing (SEC/exchange) → prefer it over news/web
    - If numeric values differ by < 5% → merge (average or keep higher-trust)
    - Otherwise → uncertain (flag for human review)
    """

    def __init__(self, model=None, tools=None):
        super().__init__(name="AdjudicatorAgent", model=model, tools=tools or {})

    def get_capabilities(self) -> List[str]:
        return ["source_conflict_resolution", "claim_adjudication", "evidence_deduplication"]

    def execute_task(self, task: AgentTask) -> TaskResult:
        return self.run(task)

    def run(self, task: AgentTask) -> TaskResult:
        params = task.parameters or {}
        gap_id: str = str(params.get("gap_id", ""))
        gap_description: str = str(params.get("gap_description", ""))
        conflicting_claims: List[Dict[str, Any]] = params.get("conflicting_claims", [])
        conflicting_evidence: List[Dict[str, Any]] = params.get("conflicting_evidence", [])
        symbol: str = str(params.get("symbol", ""))

        decisions: List[Dict[str, Any]] = []

        # Adjudicate conflicting claims
        if len(conflicting_claims) >= 2:
            decision = _adjudicate_claims(conflicting_claims[0], conflicting_claims[1], symbol)
            decisions.append({
                "gap_id": gap_id,
                "conflict_type": "claim",
                "decision": decision["verdict"],
                "kept_claim_id": decision.get("kept_id"),
                "merged_claim": decision.get("merged_claim"),
                "reason": decision["reason"],
                "confidence": decision["confidence"],
            })

        # Adjudicate conflicting evidence
        if len(conflicting_evidence) >= 2:
            decision = _adjudicate_evidence(conflicting_evidence[0], conflicting_evidence[1])
            decisions.append({
                "gap_id": gap_id,
                "conflict_type": "evidence",
                "decision": decision["verdict"],
                "kept_evidence_id": decision.get("kept_id"),
                "reason": decision["reason"],
                "confidence": decision["confidence"],
            })

        # If no specific conflicts provided, produce a generic uncertain verdict
        if not decisions:
            decisions.append({
                "gap_id": gap_id,
                "conflict_type": "unknown",
                "decision": UNCERTAIN,
                "reason": f"SOURCE_CONFLICT gap '{gap_description}' has no structured conflicting items — deferred to final rewrite.",
                "confidence": 0.0,
            })

        return TaskResult(
            task_id=task.task_id,
            agent_name=self.name,
            status=AgentStatus.COMPLETED,
            output={
                "adjudication_decisions": decisions,
                "gap_id": gap_id,
                "resolved_count": sum(1 for d in decisions if d["decision"] != UNCERTAIN),
                "uncertain_count": sum(1 for d in decisions if d["decision"] == UNCERTAIN),
            },
        )


# ─── Rule-based adjudication helpers ──────────────────────────────────────

_TRUST_RANK = {"high": 3, "medium": 2, "low": 1, "": 0}
_FILING_SOURCE_TYPES = frozenset({"filing", "sec_filing", "exchange_filing", "10-k", "10-q", "8-k", "annual_report"})


def _trust_score(item: Dict[str, Any]) -> int:
    trust = str(item.get("trust_level", "")).lower()
    source_type = str(item.get("source_type", "")).lower()
    base = _TRUST_RANK.get(trust, 0)
    # Filings get a +1 bonus over news/web
    if source_type in _FILING_SOURCE_TYPES:
        base += 1
    return base


def _adjudicate_claims(claim_a: Dict[str, Any], claim_b: Dict[str, Any], symbol: str) -> Dict[str, Any]:
    score_a = _trust_score(claim_a)
    score_b = _trust_score(claim_b)
    id_a = str(claim_a.get("claim_id", "claim_a"))
    id_b = str(claim_b.get("claim_id", "claim_b"))

    # Try numeric comparison if both have numeric_values
    nums_a = claim_a.get("numeric_values", {})
    nums_b = claim_b.get("numeric_values", {})
    shared_keys = set(nums_a) & set(nums_b)
    if shared_keys:
        key = next(iter(shared_keys))
        try:
            val_a = float(nums_a[key])
            val_b = float(nums_b[key])
            if val_a != 0 and abs(val_a - val_b) / abs(val_a) < 0.05:
                # Within 5% — merge by keeping higher-trust
                winner_id = id_a if score_a >= score_b else id_b
                return {
                    "verdict": MERGE,
                    "kept_id": winner_id,
                    "reason": f"Numeric values for '{key}' differ by <5% ({val_a} vs {val_b}); keeping higher-trust source.",
                    "confidence": 0.85,
                }
        except (TypeError, ValueError, ZeroDivisionError):
            pass

    if score_a > score_b:
        return {"verdict": KEEP_FIRST, "kept_id": id_a, "reason": f"claim_a has higher trust ({score_a} > {score_b})", "confidence": 0.8}
    if score_b > score_a:
        return {"verdict": KEEP_SECOND, "kept_id": id_b, "reason": f"claim_b has higher trust ({score_b} > {score_a})", "confidence": 0.8}
    return {"verdict": UNCERTAIN, "kept_id": None, "reason": "Equal trust scores; cannot auto-adjudicate.", "confidence": 0.3}


def _adjudicate_evidence(ev_a: Dict[str, Any], ev_b: Dict[str, Any]) -> Dict[str, Any]:
    score_a = _trust_score(ev_a)
    score_b = _trust_score(ev_b)
    id_a = str(ev_a.get("evidence_id", "ev_a"))
    id_b = str(ev_b.get("evidence_id", "ev_b"))

    if score_a > score_b:
        return {"verdict": KEEP_FIRST, "kept_id": id_a, "reason": f"evidence_a has higher trust ({score_a} > {score_b})", "confidence": 0.8}
    if score_b > score_a:
        return {"verdict": KEEP_SECOND, "kept_id": id_b, "reason": f"evidence_b has higher trust ({score_b} > {score_a})", "confidence": 0.8}
    return {"verdict": UNCERTAIN, "kept_id": None, "reason": "Equal trust scores; cannot auto-adjudicate.", "confidence": 0.3}
