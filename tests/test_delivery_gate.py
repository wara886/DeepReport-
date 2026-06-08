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
