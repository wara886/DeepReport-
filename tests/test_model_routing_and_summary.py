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
    user_fast: user_fast
    developer_fast: developer_fast
  final_answer:
    preview: flash
    delivery: pro
    user_fast: user_fast
    developer_fast: developer_fast
  verifier:
    preview: flash
    delivery: pro
    user_fast: user_fast
    developer_fast: developer_fast
""".strip(),
        encoding="utf-8",
    )
    return config


def _write_routing_config_with_fast_tiers(tmp_path: Path) -> Path:
    """Full config including user_fast and developer_fast routes."""
    config = tmp_path / "model_backends_full.yaml"
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
  user_fast:
    provider: deepseek
    model_name: deepseek-v4-flash
    base_url: https://api.deepseek.com
    api_key: ""
    timeout: 30
    retry: 1
  developer_fast:
    provider: deepseek
    model_name: deepseek-v4-flash
    base_url: https://api.deepseek.com
    api_key: ""
    timeout: 30
    retry: 1
agent_model_routes:
  defaults:
    preview: flash
    delivery: flash
    user_fast: user_fast
    developer_fast: developer_fast
  chat:
    preview: flash
    delivery: flash
    user_fast: user_fast
    developer_fast: developer_fast
  planning:
    preview: flash
    delivery: flash
    user_fast: user_fast
    developer_fast: developer_fast
  research:
    preview: flash
    delivery: flash
    user_fast: user_fast
    developer_fast: developer_fast
  browser:
    preview: flash
    delivery: flash
    user_fast: user_fast
    developer_fast: developer_fast
  deep_analyze:
    preview: flash
    delivery: pro
    user_fast: user_fast
    developer_fast: developer_fast
  final_answer:
    preview: flash
    delivery: pro
    user_fast: user_fast
    developer_fast: developer_fast
  verifier:
    preview: flash
    delivery: pro
    user_fast: user_fast
    developer_fast: developer_fast
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


# ── Test: user_fast tier uses flash for all roles ───────────────────────

def test_user_fast_all_roles_use_flash(monkeypatch, tmp_path):
    """user_fast 模式下所有角色都使用 user_fast profile，不出现 pro。"""
    calls: list[str] = []

    def _fake_from_profile(profile, config_path, fallback_section="agent_model"):
        del config_path, fallback_section
        calls.append(profile)
        return _StubModel(profile)

    monkeypatch.setattr(
        "src.agents.multi_agent_orchestrator.ModelAdapter.from_profile",
        staticmethod(_fake_from_profile),
    )
    config_path = _write_routing_config_with_fast_tiers(tmp_path)
    orch = MultiAgentOrchestrator(
        output_dir=str(tmp_path / "u_outputs"),
        report_dir=str(tmp_path / "u_reports"),
        config_path=str(config_path),
        execution_tier="user_fast",
    )
    assert calls == ["user_fast"] * 7, f"Expected all user_fast, got {calls}"
    for role in ("deep_analyze", "final_answer", "verifier"):
        assert orch.model_usage_by_agent[role]["route_profile"] == "user_fast", \
            f"{role} expected user_fast, got {orch.model_usage_by_agent[role]['route_profile']}"


# ── Test: developer_fast tier uses flash for all roles ──────────────────

def test_developer_fast_all_roles_use_flash(monkeypatch, tmp_path):
    """developer_fast 模式下所有角色都使用 developer_fast profile。"""
    calls: list[str] = []

    def _fake_from_profile(profile, config_path, fallback_section="agent_model"):
        del config_path, fallback_section
        calls.append(profile)
        return _StubModel(profile)

    monkeypatch.setattr(
        "src.agents.multi_agent_orchestrator.ModelAdapter.from_profile",
        staticmethod(_fake_from_profile),
    )
    config_path = _write_routing_config_with_fast_tiers(tmp_path)
    orch = MultiAgentOrchestrator(
        output_dir=str(tmp_path / "dev_outputs"),
        report_dir=str(tmp_path / "dev_reports"),
        config_path=str(config_path),
        execution_tier="developer_fast",
    )
    for role in ("deep_analyze", "final_answer", "verifier"):
        assert orch.model_usage_by_agent[role]["route_profile"] == "developer_fast", \
            f"{role} expected developer_fast, got {orch.model_usage_by_agent[role]['route_profile']}"


# ── Test: delivery tier still uses pro for critical roles ───────────────

def test_delivery_tier_uses_pro_for_critical_roles(monkeypatch, tmp_path):
    """delivery 模式下 deep_analyze/final_answer/verifier 依然使用 pro。"""
    calls: list[str] = []

    def _fake_from_profile(profile, config_path, fallback_section="agent_model"):
        del config_path, fallback_section
        calls.append(profile)
        return _StubModel(profile)

    monkeypatch.setattr(
        "src.agents.multi_agent_orchestrator.ModelAdapter.from_profile",
        staticmethod(_fake_from_profile),
    )
    config_path = _write_routing_config_with_fast_tiers(tmp_path)
    orch = MultiAgentOrchestrator(
        output_dir=str(tmp_path / "del_outputs"),
        report_dir=str(tmp_path / "del_reports"),
        config_path=str(config_path),
        execution_tier="delivery",
    )
    assert calls == ["flash", "flash", "flash", "flash", "pro", "pro", "pro"], \
        f"Expected delivery routing, got {calls}"
    for role in ("deep_analyze", "final_answer", "verifier"):
        assert orch.model_usage_by_agent[role]["route_profile"] == "pro", \
            f"{role} expected pro, got {orch.model_usage_by_agent[role]['route_profile']}"


# ── Test: user_fast ignores delivery fallback ───────────────────────────

def test_user_fast_ignores_delivery_fallback(monkeypatch, tmp_path):
    """user_fast 模式下即使 YAML 缺少 user_fast 路由，也不 fallback 到 delivery/pro。"""
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
    orch = MultiAgentOrchestrator(
        output_dir=str(tmp_path / "fb_outputs"),
        report_dir=str(tmp_path / "fb_reports"),
        config_path=str(config_path),
        execution_tier="user_fast",
    )
    for role in ("deep_analyze", "final_answer", "verifier"):
        assert orch.model_usage_by_agent[role]["route_profile"] == "user_fast", \
            f"{role} expected user_fast, got {orch.model_usage_by_agent[role]['route_profile']}"
