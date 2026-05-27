import json
from pathlib import Path

from src.agents.multi_agent_orchestrator import MultiAgentOrchestrator


class _StubModel:
    def __init__(self, profile: str):
        self.model_name = f"{profile}-model"
        self.route_profile = profile
        self.model_fallback_used = False
        self.api_key = ""


def _write_routing_config(tmp_path: Path) -> Path:
    config = tmp_path / "model_backends.yaml"
    config.write_text(
        """
agent_model:
  provider: deepseek
  model_name: deepseek-fallback
  base_url: https://api.deepseek.com
  api_key: ""
model_profiles:
  flash:
    provider: deepseek
    model_name: deepseek-v4-flash
    base_url: https://api.deepseek.com
    api_key: ""
  pro:
    provider: deepseek
    model_name: deepseek-v4-pro
    base_url: https://api.deepseek.com
    api_key: ""
agent_model_routes:
  defaults:
    preview: flash
    delivery: flash
  chat:
    preview: flash
    delivery: flash
  planning:
    preview: flash
    delivery: flash
  research:
    preview: flash
    delivery: flash
  browser:
    preview: flash
    delivery: flash
  deep_analyze:
    preview: flash
    delivery: pro
  final_answer:
    preview: flash
    delivery: pro
  verifier:
    preview: flash
    delivery: pro
""".strip(),
        encoding="utf-8",
    )
    return config


def test_orchestrator_model_routes_respect_execution_tier(monkeypatch, tmp_path):
    calls: list[str] = []

    def _fake_from_profile(profile, config_path, fallback_section="agent_model"):
        del config_path, fallback_section
        calls.append(profile)
        return _StubModel(profile)

    monkeypatch.setattr(
        "src.agents.multi_agent_orchestrator.ModelAdapter.from_profile",
        staticmethod(_fake_from_profile),
    )
    config_path = _write_routing_config(tmp_path)

    delivery = MultiAgentOrchestrator(
        output_dir=str(tmp_path / "delivery_outputs"),
        report_dir=str(tmp_path / "delivery_reports"),
        config_path=str(config_path),
        execution_tier="delivery",
    )
    assert calls == ["flash", "flash", "flash", "flash", "pro", "pro", "pro"]
    assert delivery.model_usage_by_agent["deep_analyze"]["route_profile"] == "pro"
    assert delivery.model_usage_by_agent["final_answer"]["route_profile"] == "pro"
    assert delivery.model_usage_by_agent["verifier"]["route_profile"] == "pro"
    assert delivery.model_usage_by_agent["identity"]["model_enabled"] is False
    assert delivery.model_usage_by_agent["gap_resolver"]["route_profile"] == "rule_only"

    calls.clear()
    preview = MultiAgentOrchestrator(
        output_dir=str(tmp_path / "preview_outputs"),
        report_dir=str(tmp_path / "preview_reports"),
        config_path=str(config_path),
        execution_tier="preview",
    )
    assert calls == ["flash", "flash", "flash", "flash", "flash", "flash", "flash"]
    assert preview.model_usage_by_agent["deep_analyze"]["route_profile"] == "flash"


def test_runtime_execution_summary_tracks_registered_and_executed_agents(monkeypatch, tmp_path):
    def _fake_from_profile(profile, config_path, fallback_section="agent_model"):
        del config_path, fallback_section
        return _StubModel(profile)

    monkeypatch.setattr(
        "src.agents.multi_agent_orchestrator.ModelAdapter.from_profile",
        staticmethod(_fake_from_profile),
    )
    config_path = _write_routing_config(tmp_path)
    orchestrator = MultiAgentOrchestrator(
        output_dir=str(tmp_path / "outputs"),
        report_dir=str(tmp_path / "reports"),
        config_path=str(config_path),
        execution_tier="delivery",
    )

    orchestrator.trace = [
        {"agent_key": "planning", "status": "completed"},
        {"agent_key": "research", "status": "completed"},
        {"agent_key": "planning", "status": "completed"},
        {"agent": "FinalAnswerAgent", "status": "completed"},
    ]
    summary = orchestrator._runtime_execution_summary()
    assert summary["registered_agent_count"] == 13
    assert summary["executed_agent_count"] == 3
    assert summary["executed_agents"] == ["planning", "research", "final_answer"]
    assert set(summary["model_usage_by_agent"].keys()) == {"planning", "research", "final_answer"}

    summary_path = tmp_path / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
    persisted = json.loads(summary_path.read_text(encoding="utf-8"))
    assert persisted["executed_agent_count"] == 3
