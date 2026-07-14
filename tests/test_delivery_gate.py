import json

from src.evaluation.delivery_gate import build_delivery_gate, write_delivery_gate


def test_delivery_gate_requires_all_three_gates(tmp_path):
    outputs = tmp_path / "run" / "company" / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "run_summary.json").write_text('{"verification_passed": true}', encoding="utf-8")
    (outputs / "verification_report.json").write_text('{"passed": true}', encoding="utf-8")
    (outputs / "quality_report.json").write_text('{"objective_pass": true, "total_score": 0.9}', encoding="utf-8")
    (outputs / "llm_quality_review.json").write_text('{"llm_review_pass": false, "total_score": 0.0, "issues": [{"severity": "fatal", "message": "missing API key"}]}', encoding="utf-8")

    gate = build_delivery_gate(tmp_path / "run")
    paths = write_delivery_gate(tmp_path / "run", gate)

    assert gate["delivery_pass"] is False
    assert gate["diagnostic_delivery_pass"] is False
    assert gate["diagnostic_only"] is True
    assert gate["status"] == "completed"
    assert gate["verifier_passed"] is True
    assert gate["objective_pass"] is True
    assert gate["llm_review_pass"] is False
    assert gate["issue_counts"]["fatal"] == 1
    assert paths["delivery_gate"].endswith("delivery_gate.json")


def test_delivery_gate_passes_when_all_gates_pass(tmp_path):
    outputs = tmp_path / "run" / "company" / "outputs"
    outputs.mkdir(parents=True)
    for name, payload in {
        "verification_report.json": {"passed": True},
        "quality_report.json": {"objective_pass": True, "total_score": 0.88, "issues": []},
        "llm_quality_review.json": {"llm_review_pass": True, "total_score": 0.84, "issues": []},
    }.items():
        (outputs / name).write_text(json.dumps(payload), encoding="utf-8")

    gate = build_delivery_gate(tmp_path / "run")

    assert gate["delivery_pass"] is True
    assert gate["status"] == "completed"
    assert gate["issue_counts"]["fatal"] == 0


def test_delivery_gate_relaxes_llm_score_when_review_passes_without_blockers(tmp_path):
    outputs = tmp_path / "run" / "company" / "outputs"
    outputs.mkdir(parents=True)
    for name, payload in {
        "verification_report.json": {"passed": True},
        "quality_report.json": {"objective_pass": True, "total_score": 0.96, "issues": []},
        "llm_quality_review.json": {
            "llm_review_pass": True,
            "total_score": 0.72,
            "issues": [{"severity": "warning", "category": "valuation", "message": "model output needs clearer citation"}],
        },
    }.items():
        (outputs / name).write_text(json.dumps(payload), encoding="utf-8")

    gate = build_delivery_gate(tmp_path / "run")

    assert gate["delivery_pass"] is True
    assert gate["gate_requirements"]["llm_review_strict_score_pass"] is False
    assert gate["gate_requirements"]["llm_review_relaxed_score_pass"] is True


def test_delivery_gate_keeps_llm_pass_independent_from_non_llm_contract_blocker(tmp_path):
    outputs = tmp_path / "run" / "company" / "outputs"
    outputs.mkdir(parents=True)
    fixtures = {
        "verification_report.json": {"passed": True},
        "quality_report.json": {"objective_pass": True, "total_score": 0.96, "issues": []},
        "llm_quality_review.json": {"llm_review_pass": True, "total_score": 0.86, "issues": []},
        "report_section_contracts.json": {"contracts": {"valuation": {"quality_flags": ["hard_valuation_gap", "hard_market_gap"]}}},
    }
    for name, payload in fixtures.items():
        (outputs / name).write_text(json.dumps(payload), encoding="utf-8")

    gate = build_delivery_gate(tmp_path / "run")

    assert gate["llm_review_pass"] is True
    assert gate["delivery_pass"] is False
    assert any(issue["category"] == "contract" and issue["severity"] == "blocker" for issue in gate["issues"])


def test_delivery_gate_treats_skipped_pdf_gap_summary_as_nonblocking(tmp_path):
    outputs = tmp_path / "run" / "company" / "outputs"
    outputs.mkdir(parents=True)
    fixtures = {
        "verification_report.json": {"passed": True},
        "quality_report.json": {"objective_pass": True, "total_score": 0.96, "issues": []},
        "llm_quality_review.json": {"llm_review_pass": True, "total_score": 0.86, "issues": []},
        "report_section_contracts.json": {"contracts": {"business_overview": {
            "status": "supported",
            "quality_flags": ["business_overview_gap_summary_skipped", "business_overview_uses_sec_10k"],
        }}},
    }
    for name, payload in fixtures.items():
        (outputs / name).write_text(json.dumps(payload), encoding="utf-8")

    gate = build_delivery_gate(tmp_path / "run")

    assert gate["delivery_pass"] is True
    assert not any(issue["category"] == "contract" for issue in gate["issues"])


def test_delivery_gate_treats_nonblocking_evidence_gap_as_warning(tmp_path):
    outputs = tmp_path / "run" / "company" / "outputs"
    outputs.mkdir(parents=True)
    for name, payload in {
        "verification_report.json": {
            "passed": True,
            "evidence_gaps": [
                {
                    "description": "period-matched structured financial data fallback",
                    "blocking": False,
                }
            ],
        },
        "quality_report.json": {"objective_pass": True, "total_score": 0.96, "issues": []},
        "llm_quality_review.json": {"llm_review_pass": True, "total_score": 0.82, "issues": []},
    }.items():
        (outputs / name).write_text(json.dumps(payload), encoding="utf-8")

    gate = build_delivery_gate(tmp_path / "run")

    assert gate["delivery_pass"] is True
    assert gate["issue_counts"]["blocker"] == 0
    assert gate["issue_counts"]["warning"] == 1


def test_delivery_gate_blocks_formal_delivery_on_content_depth_blocker(tmp_path):
    outputs = tmp_path / "run" / "company" / "outputs"
    outputs.mkdir(parents=True)
    for name, payload in {
        "verification_report.json": {"passed": True},
        "quality_report.json": {
            "objective_pass": True,
            "total_score": 0.92,
            "issues": [
                {
                    "severity": "blocker",
                    "category": "content_depth",
                    "message": "执行摘要 content insufficient: only 36 chars",
                }
            ],
        },
        "llm_quality_review.json": {"llm_review_pass": True, "total_score": 0.86, "issues": []},
    }.items():
        (outputs / name).write_text(json.dumps(payload), encoding="utf-8")

    gate = build_delivery_gate(tmp_path / "run")

    assert gate["delivery_pass"] is False
    assert gate["diagnostic_delivery_pass"] is False
    assert gate["blocker_counts"]["content_depth"] == 1
    assert gate["gate_requirements"]["content_depth_blocks_formal_delivery"] is True


def test_delivery_gate_blocks_formal_delivery_on_section_verification_failure(tmp_path):
    outputs = tmp_path / "run" / "company" / "outputs"
    outputs.mkdir(parents=True)
    for name, payload in {
        "verification_report.json": {"passed": True},
        "quality_report.json": {"objective_pass": True, "total_score": 0.96, "issues": []},
        "llm_quality_review.json": {"llm_review_pass": True, "total_score": 0.86, "issues": []},
        "section_verification.json": {
            "status": "failed",
            "formal_delivery_allowed": False,
            "issues": [
                {
                    "issue_id": "section_contract_conclusion_section_too_short",
                    "severity": "blocker",
                    "category": "section_contract",
                    "section": "conclusion",
                    "message": "投资结论 failed section contract: section_too_short",
                }
            ],
        },
    }.items():
        (outputs / name).write_text(json.dumps(payload), encoding="utf-8")

    gate = build_delivery_gate(tmp_path / "run")

    assert gate["delivery_pass"] is False
    assert gate["diagnostic_delivery_pass"] is False
    assert gate["gate_requirements"]["section_verification_passed"] is False
    assert any(issue["source"] == "section_verification" for issue in gate["issues"])


def test_delivery_gate_ignores_nonblocking_contract_fallback_flags(tmp_path):
    outputs = tmp_path / "run" / "company" / "outputs"
    outputs.mkdir(parents=True)
    for name, payload in {
        "verification_report.json": {"passed": True},
        "quality_report.json": {"objective_pass": True, "total_score": 0.96, "issues": []},
        "llm_quality_review.json": {"llm_review_pass": True, "total_score": 0.86, "issues": []},
        "section_verification.json": {"status": "passed", "formal_delivery_allowed": True},
        "report_section_contracts.json": {
            "contracts": {
                "business_overview": {
                    "status": "partial",
                    "blocked_reasons": ["business_overview_used_profile_fallback"],
                    "quality_flags": ["business_overview_evidence_fallback"],
                },
                "valuation": {"status": "partial", "quality_flags": ["valuation_directional_only"]},
            }
        },
    }.items():
        (outputs / name).write_text(json.dumps(payload), encoding="utf-8")

    gate = build_delivery_gate(tmp_path / "run")

    assert gate["delivery_pass"] is True
    assert not any(issue["category"] == "contract" for issue in gate["issues"])


def test_delivery_gate_demotes_boundary_contract_blockers_after_objective_pass(tmp_path):
    outputs = tmp_path / "run" / "company" / "outputs"
    outputs.mkdir(parents=True)
    for name, payload in {
        "verification_report.json": {"passed": True},
        "quality_report.json": {"objective_pass": True, "total_score": 0.96, "issues": []},
        "llm_quality_review.json": {"llm_review_pass": True, "total_score": 0.86, "issues": []},
        "section_verification.json": {"status": "passed", "formal_delivery_allowed": True},
        "report_section_contracts.json": {
            "contracts": {
                "ownership_governance": {
                    "blocked_reasons": ["governance_section_not_found"],
                    "quality_flags": ["governance_uses_sec_proxy"],
                },
                "strategy_business": {"blocked_reasons": ["strategy_pdf_sections_not_found"]},
                "valuation_sensitivity": {"quality_flags": ["valuation_sensitivity_framework_only"]},
                "period_note": {"quality_flags": ["period_mismatch"]},
                "risk_factors": {
                    "blocked_reasons": ["risk_official_pdf_not_found_and_no_industry_fallback"],
                    "quality_flags": ["risk_generic_fallback_no_industry_policy"],
                },
            }
        },
    }.items():
        (outputs / name).write_text(json.dumps(payload), encoding="utf-8")

    gate = build_delivery_gate(tmp_path / "run")

    assert gate["delivery_pass"] is True
    assert gate["issue_counts"]["blocker"] == 0
    assert any(issue["category"] == "contract" and issue["severity"] == "warning" for issue in gate["issues"])


def test_delivery_gate_requires_objective_pass_even_when_scores_are_high(tmp_path):
    outputs = tmp_path / "run" / "company" / "outputs"
    outputs.mkdir(parents=True)
    for name, payload in {
        "verification_report.json": {"passed": True},
        "quality_report.json": {"objective_pass": False, "total_score": 0.95, "issues": []},
        "llm_quality_review.json": {"llm_review_pass": True, "total_score": 0.87, "issues": []},
    }.items():
        (outputs / name).write_text(json.dumps(payload), encoding="utf-8")

    gate = build_delivery_gate(tmp_path / "run")

    assert gate["delivery_pass"] is False
    assert gate["objective_pass"] is False
    assert any(
        issue["category"] == "objective_quality" and issue["severity"] == "blocker"
        for issue in gate["issues"]
    )


def test_delivery_gate_explains_verifier_boolean_failure_with_blocker(tmp_path):
    outputs = tmp_path / "run" / "company" / "outputs"
    outputs.mkdir(parents=True)
    for name, payload in {
        "verification_report.json": {"passed": False, "warnings": []},
        "quality_report.json": {"objective_pass": True, "total_score": 0.95, "issues": []},
        "llm_quality_review.json": {"llm_review_pass": True, "total_score": 0.9, "issues": []},
    }.items():
        (outputs / name).write_text(json.dumps(payload), encoding="utf-8")

    gate = build_delivery_gate(tmp_path / "run")

    assert gate["machine_quality_pass"] is False
    assert any(issue["category"] == "verifier" and issue["severity"] == "blocker" for issue in gate["issues"])


def test_delivery_gate_never_emits_none_message_and_enforces_llm_score(tmp_path):
    outputs = tmp_path / "run" / "company" / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "verification_report.json").write_text(
        json.dumps({"passed": True, "evidence_gaps": [{"claim_id": "cl_1", "message": None}]}),
        encoding="utf-8",
    )
    (outputs / "quality_report.json").write_text(json.dumps({"objective_pass": True, "total_score": 0.9}), encoding="utf-8")
    (outputs / "llm_quality_review.json").write_text(
        json.dumps({"llm_review_pass": True, "total_score": 0.79, "issues": []}),
        encoding="utf-8",
    )

    gate = build_delivery_gate(tmp_path / "run")

    assert gate["delivery_pass"] is False
    assert gate["diagnostic_delivery_pass"] is False
    assert gate["llm_review_pass"] is False
    assert gate["gate_requirements"]["llm_review_score_pass"] is False
    assert all(item["message"] and item["message"] != "None" for item in gate["issues"])


def test_delivery_gate_write_sanitizes_control_chars_and_nan(tmp_path):
    outputs = tmp_path / "run" / "company" / "outputs"
    outputs.mkdir(parents=True)
    gate = {
        "delivery_pass": False,
        "scores": {"llm_total_score": float("nan")},
        "issues": [{"severity": "fatal", "category": "llm_review", "message": "bad\x01message"}],
    }

    paths = write_delivery_gate(tmp_path / "run", gate)
    parsed = json.loads(open(paths["delivery_gate"], encoding="utf-8").read())

    assert parsed["scores"]["llm_total_score"] is None
    assert "\x01" not in parsed["issues"][0]["message"]
