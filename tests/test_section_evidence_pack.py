import json

from src.evaluation.delivery_gate import build_delivery_gate
from src.evaluation.section_evidence_pack import build_section_evidence_packs
from src.evaluation.section_verification import build_section_verification


def test_section_pack_builds_must_use_evidence_and_claim_support(tmp_path):
    (tmp_path / "report_section_contracts.json").write_text(json.dumps({
        "contracts": {"conclusion": {"title": "投资结论", "citation_evidence_ids": ["ev1", "missing"]}}
    }), encoding="utf-8")
    (tmp_path / "section_dossiers.json").write_text(json.dumps({
        "conclusion": {"supported_claims": [{"claim_id": "cl1"}], "supporting_evidence_ids": ["ev1"]}
    }), encoding="utf-8")
    (tmp_path / "claims.json").write_text(json.dumps([
        {"claim_id": "cl1", "section_name": "conclusion", "claim_text": "结论", "evidence_ids": ["ev1"]}
    ]), encoding="utf-8")
    (tmp_path / "evidence.json").write_text(json.dumps([
        {"evidence_id": "ev1", "period": "FY2024", "source_authority": "official", "source_type": "official_filing"}
    ]), encoding="utf-8")

    artifact = build_section_evidence_packs(tmp_path)

    pack = artifact["packs"]["conclusion"]
    assert pack["must_use_evidence_ids"] == ["ev1"]
    assert pack["missing_evidence_ids"] == ["missing"]
    assert pack["claims"][0]["verification_status"] == "supported"
    assert (tmp_path / "section_evidence_packs.json").exists()


def test_section_pack_merges_risk_and_conclusion_aliases_without_losing_inputs(tmp_path):
    (tmp_path / "report_section_contracts.json").write_text(json.dumps({
        "contracts": {
            "risks": {"title": "风险评估", "citation_evidence_ids": ["risk-1"]},
            "risk_factors": {"citation_evidence_ids": ["risk-2"], "blocked_reasons": ["needs detail"]},
            "conclusion": {"title": "投资结论", "citation_evidence_ids": ["conclusion-1"]},
            "investment_conclusion": {"citation_evidence_ids": ["conclusion-2"]},
        }
    }), encoding="utf-8")
    (tmp_path / "section_dossiers.json").write_text(json.dumps({
        "risk_factors": {"supported_claims": [{"claim_id": "risk-claim"}]},
        "investment_conclusion": {"supported_claims": [{"claim_id": "conclusion-claim"}]},
    }), encoding="utf-8")
    (tmp_path / "claims.json").write_text(json.dumps([
        {"claim_id": "risk-claim", "section_name": "risk_factors", "evidence_ids": ["risk-2"]},
        {"claim_id": "conclusion-claim", "section_name": "investment_conclusion", "evidence_ids": ["conclusion-2"]},
    ]), encoding="utf-8")
    (tmp_path / "evidence.json").write_text(json.dumps([
        {"evidence_id": evidence_id}
        for evidence_id in ("risk-1", "risk-2", "conclusion-1", "conclusion-2")
    ]), encoding="utf-8")

    artifact = build_section_evidence_packs(tmp_path)

    assert set(artifact["packs"]) == {"risks", "conclusion"}
    assert artifact["packs"]["risks"]["must_use_evidence_ids"] == ["risk-2", "risk-1"]
    assert artifact["packs"]["risks"]["claims"][0]["claim_id"] == "risk-claim"
    assert artifact["packs"]["conclusion"]["must_use_evidence_ids"] == ["conclusion-2", "conclusion-1"]
    assert artifact["packs"]["conclusion"]["claims"][0]["claim_id"] == "conclusion-claim"


def test_section_verification_distinguishes_citation_from_supported_claim():
    markdown = "# 报告\n\n## 投资结论\n" + ("结论内容充分且包含证据支持。" * 20) + "[ev1]\n"
    packs = {"packs": {"conclusion": {
        "must_use_evidence_ids": ["ev1"],
        "must_use_evidence": [{"evidence_id": "ev1", "period": "FY2024", "authority": "official"}],
        "unsupported_claim_ids": ["cl_bad"],
    }}}

    result = build_section_verification(markdown=markdown, section_evidence_packs=packs)

    conclusion = result["section_results"]["conclusion"]
    assert conclusion["citation_present"] is True
    assert conclusion["claim_supported"] is False
    assert "unsupported_claims" in conclusion["reasons"]


def test_delivery_gate_blocks_stale_verification_when_pack_claim_is_unsupported(tmp_path):
    outputs = tmp_path / "run" / "company" / "outputs"
    outputs.mkdir(parents=True)
    fixtures = {
        "verification_report.json": {"passed": True},
        "quality_report.json": {"objective_pass": True, "total_score": 0.96, "issues": []},
        "llm_quality_review.json": {"llm_review_pass": True, "total_score": 0.86, "issues": []},
        "section_verification.json": {"status": "passed", "formal_delivery_allowed": True, "section_results": {"conclusion": {"consumed_evidence_ids": ["ev1"]}}},
        "section_evidence_packs.json": {"packs": {"conclusion": {"must_use_evidence_ids": ["ev1"], "unsupported_claim_ids": ["cl_bad"]}}},
    }
    for name, payload in fixtures.items():
        (outputs / name).write_text(json.dumps(payload), encoding="utf-8")

    gate = build_delivery_gate(tmp_path / "run")

    assert gate["delivery_pass"] is False
    assert any(issue["category"] == "claim_support" for issue in gate["issues"])
