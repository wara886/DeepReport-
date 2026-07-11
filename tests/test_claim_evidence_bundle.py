"""Tests for ClaimEvidenceBundle and DerivedEvidenceBuilder."""

from pathlib import Path
from typing import Any, Dict, List

from src.agents.claim_evidence_bundle import build_claim_evidence_bundles
from src.agents.derived_evidence_builder import build_derived_evidence


# ── DerivedEvidenceBuilder tests ──────────────────────────────────────


def test_derived_evidence_from_financial_metrics():
    """build_derived_evidence extracts financial_metrics from analysis_artifacts."""
    state: Dict[str, Any] = {
        "symbol": "AAPL",
        "period": "FY2024",
        "claims": [{"claim_id": "cl_001", "claim_text": "revenue grew"}],
        "evidence_records": [{"evidence_id": "sec_001", "title": "SEC filing"}],
        "analysis_artifacts": {
            "financial_metrics": {
                "revenue": 395000000000,
                "net_income": 97000000000,
                "metric_count": 15,
            },
        },
        "research_blackboard": {},
    }
    derived = build_derived_evidence(state)
    metrics_evidence = [d for d in derived if "financial_metrics" in d["evidence_id"]]
    assert len(metrics_evidence) == 1, f"Expected 1 financial metric evidence, got {len(metrics_evidence)}"
    me = metrics_evidence[0]
    assert me["source_type"] == "internal_model"
    assert me["trust_level"] == "derived"
    assert me["symbol"] == "AAPL"
    assert me["period"] == "FY2024"
    assert "395000000000" in me["content"]
    assert "sec_001" in str(me["input_evidence_ids"])


def test_derived_evidence_from_valuation():
    """build_derived_evidence extracts valuation from analysis_artifacts."""
    state: Dict[str, Any] = {
        "symbol": "TSLA",
        "period": "2026Q1",
        "claims": [],
        "evidence_records": [],
        "analysis_artifacts": {
            "valuation": {
                "dcf_value": 320.50,
                "pe_ratio": 45.2,
                "assumptions": ["WACC=10%", "growth=15%"],
                "limitations": ["DCF sensitive to terminal growth"],
            },
        },
        "research_blackboard": {},
    }
    derived = build_derived_evidence(state)
    val_evidence = [d for d in derived if "valuation" in d["evidence_id"]]
    assert len(val_evidence) == 1
    ve = val_evidence[0]
    assert ve["trust_level"] == "derived"
    assert "dcf_value" in ve["content"] or "320.5" in ve["content"]
    assert "WACC=10%" in str(ve["assumptions"])
    assert "DCF sensitive" in str(ve["limitations"])


def test_derived_evidence_from_valuation_model_and_sensitivity():
    state: Dict[str, Any] = {
        "symbol": "AAPL",
        "period": "FY2024",
        "claims": [],
        "evidence_records": [{"evidence_id": "ev_cash_flow"}],
        "analysis_artifacts": {
            "valuation_model": {
                "dcf_model": {"equity_value_billion": 2452.91},
                "target_price": 167.01,
            },
            "valuation_sensitivity": {
                "scenario_values": {
                    "bear": {"equity_value_billion": 1986.77},
                    "base": {"equity_value_billion": 2452.91},
                    "bull": {"equity_value_billion": 3086.92},
                }
            },
        },
        "research_blackboard": {},
    }

    derived = build_derived_evidence(state)
    by_id = {item["evidence_id"]: item for item in derived}

    assert "internal_valuation_AAPL_FY2024_v1" in by_id
    assert "internal_valuation_sensitivity_AAPL_FY2024_v1" in by_id
    assert by_id["internal_valuation_sensitivity_AAPL_FY2024_v1"]["source_type"] == "internal_model"
    assert "ev_cash_flow" in str(by_id["internal_valuation_sensitivity_AAPL_FY2024_v1"]["input_evidence_ids"])


def test_derived_evidence_from_peer_analysis():
    """build_derived_evidence extracts peer analysis from research_blackboard."""
    state: Dict[str, Any] = {
        "symbol": "MSFT",
        "period": "FY2024",
        "claims": [],
        "evidence_records": [],
        "analysis_artifacts": {},
        "research_blackboard": {
            "peer_analysis": {
                "peers": ["AAPL", "GOOGL", "AMZN"],
                "msft_pe": 35.0,
                "avg_pe": 30.0,
            },
        },
    }
    derived = build_derived_evidence(state)
    peer_evidence = [d for d in derived if "peer" in d["evidence_id"]]
    assert len(peer_evidence) == 1
    pe = peer_evidence[0]
    assert pe["source_type"] == "internal_model"
    assert "MSFT" in pe["evidence_id"]


def test_derived_evidence_empty_state():
    """build_derived_evidence handles empty state gracefully."""
    derived = build_derived_evidence({})
    assert derived == []


# ── ClaimEvidenceBundle tests ─────────────────────────────────────────


def test_claim_bundle_grounded():
    """Claim with high-trust evidence is classified as grounded."""
    claims: List[Dict[str, Any]] = [
        {"claim_id": "cl_001", "section_name": "valuation", "claim_text": "Revenue grew 10%", "evidence_ids": ["ev_001"]},
    ]
    evidence: List[Dict[str, Any]] = [
        {"evidence_id": "ev_001", "content": "Revenue was $100B, up 10% YoY", "source_type": "filing", "trust_level": "high"},
    ]
    bundles = build_claim_evidence_bundles(claims, evidence, [])
    assert len(bundles) == 1
    b = bundles[0]
    assert b["grounding_status"] == "grounded"
    assert b["allowed_in_report"] is True
    assert len(b["supporting_evidence"]) == 1
    assert b["supporting_evidence"][0]["evidence_id"] == "ev_001"


def test_claim_bundle_grounded_derived():
    """Derived evidence (internal_model) counts as high-trust for grounding."""
    claims: List[Dict[str, Any]] = [
        {"claim_id": "cl_002", "claim_text": "Valuation indicates upside", "evidence_ids": ["derived_val_001"]},
    ]
    evidence: List[Dict[str, Any]] = []
    derived: List[Dict[str, Any]] = [
        {"evidence_id": "derived_val_001", "content": "DCF target $350", "source_type": "internal_model", "trust_level": "derived"},
    ]
    bundles = build_claim_evidence_bundles(claims, evidence, derived)
    assert len(bundles) == 1
    assert bundles[0]["grounding_status"] == "grounded"


def test_claim_bundle_partial():
    """Claim with only low-trust evidence is classified as partial."""
    claims: List[Dict[str, Any]] = [
        {"claim_id": "cl_003", "claim_text": "Stock may rise", "evidence_ids": ["web_001"]},
    ]
    evidence: List[Dict[str, Any]] = [
        {"evidence_id": "web_001", "content": "Analyst says buy", "source_type": "web_or_news", "trust_level": "low"},
    ]
    bundles = build_claim_evidence_bundles(claims, evidence, [])
    assert bundles[0]["grounding_status"] == "partial"
    assert bundles[0]["allowed_in_report"] is True


def test_claim_bundle_unverified():
    """Claim with no evidence_ids or broken references is unverified."""
    claims: List[Dict[str, Any]] = [
        {"claim_id": "cl_004", "claim_text": "Made up claim", "evidence_ids": ["nonexistent"]},
    ]
    bundles = build_claim_evidence_bundles(claims, [], [])
    assert bundles[0]["grounding_status"] == "unverified"
    assert bundles[0]["allowed_in_report"] is False


def test_claim_bundle_unverified_no_evidence_ids():
    """Claim without any evidence_ids is unverified."""
    claims: List[Dict[str, Any]] = [
        {"claim_id": "cl_005", "claim_text": "No support", "evidence_ids": []},
    ]
    bundles = build_claim_evidence_bundles(claims, [], [])
    assert bundles[0]["grounding_status"] == "unverified"
    assert bundles[0]["allowed_in_report"] is False


def test_claim_bundle_empty_claims():
    """Empty claims list produces empty bundles."""
    assert build_claim_evidence_bundles([], [], []) == []


def test_claim_bundle_mixed_grounding():
    """Multiple claims get correct per-claim grounding status."""
    claims: List[Dict[str, Any]] = [
        {"claim_id": "cl_good", "claim_text": "Well supported", "evidence_ids": ["ev_high"]},
        {"claim_id": "cl_bad", "claim_text": "No support", "evidence_ids": []},
    ]
    evidence: List[Dict[str, Any]] = [
        {"evidence_id": "ev_high", "content": "Solid data", "source_type": "filing", "trust_level": "high"},
    ]
    bundles = build_claim_evidence_bundles(claims, evidence, [])
    assert len(bundles) == 2
    by_id = {b["claim_id"]: b for b in bundles}
    assert by_id["cl_good"]["grounding_status"] == "grounded"
    assert by_id["cl_good"]["allowed_in_report"] is True
    assert by_id["cl_bad"]["grounding_status"] == "unverified"
    assert by_id["cl_bad"]["allowed_in_report"] is False


# ── Integration test: derived evidence feeds into bundles ─────────────


def test_derived_evidence_feeds_into_bundles():
    """Derived evidence records are available for claim grounding."""
    state: Dict[str, Any] = {
        "symbol": "AAPL",
        "period": "FY2024",
        "claims": [{"claim_id": "cl_val", "claim_text": "Valuation is attractive", "evidence_ids": ["internal_valuation_AAPL_FY2024_v1"]}],
        "evidence_records": [],
        "analysis_artifacts": {
            "valuation": {
                "dcf_value": 250,
                "pe_ratio": 30,
            },
        },
        "research_blackboard": {},
    }
    derived = build_derived_evidence(state)
    bundles = build_claim_evidence_bundles(
        state["claims"],
        state["evidence_records"],
        derived,
    )
    assert len(bundles) == 1
    b = bundles[0]
    # The claim references the derived valuation evidence by its generated ID
    assert b["grounding_status"] in ("grounded", "partial")
