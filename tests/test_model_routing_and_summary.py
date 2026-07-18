import json
import logging
from pathlib import Path

from src.agents.base_agent import AgentStatus, AgentTask, TaskResult
from src.agents.multi_agent_orchestrator import MultiAgentOrchestrator
from src.utils.config import load_config


class _StubModel:
    def __init__(self, profile: str):
        self.model_name = f"{profile}-model"
        self.provider = "openai_compatible" if profile == "mimo_flash" else "deepseek"
        self.base_url = "https://api.xiaomimimo.com/v1" if profile == "mimo_flash" else "https://api.deepseek.com"
        self.endpoint_url = f"{self.base_url}/chat/completions"
        self.api_key_env = "MIMO_API_KEY" if profile == "mimo_flash" else "DEEPSEEK_API_KEY"
        self.route_profile = profile
        self.model_fallback_used = False
        self.api_key = ""


class _TraceAgent:
    name = "TraceAgent"

    def execute_task(self, task: AgentTask) -> TaskResult:
        return TaskResult(
            task_id=task.task_id,
            agent_name=self.name,
            status=AgentStatus.COMPLETED,
            output={"ok": True},
        )


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


def test_repository_delivery_routes_split_deepseek_and_mimo():
    config = load_config("configs/model_backends.yaml")
    routes = config["agent_model_routes"]

    for role in ("chat", "task_parser", "browser"):
        assert routes[role]["delivery"] == "mimo_flash"

    for role in ("planning", "research", "deep_analyze", "final_answer", "verifier", "llm_report_review"):
        assert routes[role]["delivery"] == "flash"


def test_repository_delivery_orchestrator_instantiates_mimo_for_light_roles(monkeypatch, tmp_path, caplog):
    calls: list[str] = []

    def _fake_from_profile(profile, config_path, fallback_section="agent_model"):
        del config_path, fallback_section
        calls.append(profile)
        return _StubModel(profile)

    monkeypatch.setattr(
        "src.agents.multi_agent_orchestrator.ModelAdapter.from_profile",
        staticmethod(_fake_from_profile),
    )

    with caplog.at_level(logging.INFO, logger="src.agents.multi_agent_orchestrator"):
        orchestrator = MultiAgentOrchestrator(
            output_dir=str(tmp_path / "outputs"),
            report_dir=str(tmp_path / "reports"),
            config_path="configs/model_backends.yaml",
            execution_tier="delivery",
        )

    assert calls == ["mimo_flash", "flash", "flash", "mimo_flash", "flash", "flash", "flash"]
    assert orchestrator.model_usage_by_agent["planning"]["route_profile"] == "flash"
    assert orchestrator.model_usage_by_agent["research"]["model_name"] == "flash-model"
    assert orchestrator.model_usage_by_agent["deep_analyze"]["route_profile"] == "flash"
    assert "model_route_summary" in caplog.text
    assert "mimo_flash-model" in caplog.text


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


def test_agent_execute_trace_includes_model_usage_and_log_line(monkeypatch, tmp_path, caplog):
    def _fake_from_profile(profile, config_path, fallback_section="agent_model"):
        del config_path, fallback_section
        return _StubModel(profile)

    monkeypatch.setattr(
        "src.agents.multi_agent_orchestrator.ModelAdapter.from_profile",
        staticmethod(_fake_from_profile),
    )
    orchestrator = MultiAgentOrchestrator(
        output_dir=str(tmp_path / "outputs"),
        report_dir=str(tmp_path / "reports"),
        config_path="configs/model_backends.yaml",
        execution_tier="delivery",
    )
    orchestrator.agents["planning"] = _TraceAgent()

    with caplog.at_level(logging.INFO, logger="src.agents.multi_agent_orchestrator"):
        result = orchestrator._execute(
            "planning",
            AgentTask(task_id="task_trace_001", task_type="planning", description="trace check"),
        )

    assert result.status == AgentStatus.COMPLETED
    assert orchestrator.trace[-1]["model_usage"]["route_profile"] == "flash"
    assert orchestrator.trace[-1]["model_usage"]["model_name"] == "flash-model"
    assert "agent_trace_start" in caplog.text
    assert "agent_trace_finish" in caplog.text
    assert "task_trace_001" in caplog.text


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


# ── Test: delivery tier respects custom pro routes ─────────────────────

def test_delivery_tier_respects_custom_pro_routes(monkeypatch, tmp_path):
    """Custom configs may still route deep_analyze/final_answer/verifier to pro."""
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
