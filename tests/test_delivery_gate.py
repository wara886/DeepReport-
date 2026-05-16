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
    assert gate["issue_counts"]["fatal"] == 0
