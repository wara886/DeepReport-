import json

from src.evaluation import delivery_pipeline


def test_delivery_quality_pipeline_returns_blocked_result_on_exception(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("pipeline failure")

    monkeypatch.setattr(delivery_pipeline, "evaluate_report_quality_from_paths", fail)

    result = delivery_pipeline.run_delivery_quality_pipeline(tmp_path / "outputs", tmp_path / "reports")

    assert result["delivery_gate"]["delivery_pass"] is False
    assert result["_quality_pipeline_exception"] == "pipeline failure"


def test_delivery_rework_loop_uses_current_orchestrator(tmp_path, monkeypatch):
    class Orchestrator:
        def __init__(self):
            self.calls = []

        def run(self, **kwargs):
            self.calls.append(kwargs)

    orchestrator = Orchestrator()
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    reports = tmp_path / "reports"
    reports.mkdir()
    (outputs / "quality_remediation_plan.json").write_text(
        json.dumps({"required_fixes": ["补写投资结论"]}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        delivery_pipeline,
        "run_delivery_quality_pipeline",
        lambda **kwargs: {"delivery_gate": {"delivery_pass": True}, "top_quality_issues": []},
    )

    result = delivery_pipeline.run_delivery_rework_loop(
        orchestrator=orchestrator,
        output_path=outputs,
        report_path=reports,
        config_path="configs/model_backends.yaml",
        initial_quality_result={
            "delivery_gate": {"delivery_pass": False},
            "top_quality_issues": [{"message": "投资结论过短"}],
        },
        run_kwargs={"symbol": "AAPL", "period": "FY2024"},
        max_rounds=1,
    )

    assert len(orchestrator.calls) == 1
    assert orchestrator.calls[0]["quality_remediation_plan"]["required_fixes"] == ["补写投资结论"]
    assert result["reworked"] is True
    assert result["quality_result"]["delivery_gate"]["delivery_pass"] is True
    history = json.loads((outputs / "delivery_rework_history.json").read_text(encoding="utf-8"))
    assert history[0]["rework_mode"] == "current_orchestrator_rerun"
