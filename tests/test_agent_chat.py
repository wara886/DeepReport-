from pathlib import Path

from src.app.agent_chat import AgentChatService, LongTermChatMemory, ShortTermChatMemory, UserPreferenceMemory


def _model_config(path: Path) -> Path:
    config = path / "model_backends.yaml"
    config.write_text(
        """
agent_model:
  provider: deepseek
  model_name: deepseek-test
  base_url: https://api.deepseek.com
  api_key: ""
  timeout: 1
  retry: 0
  max_tokens: 256
  temperature: 0.1
""".strip(),
        encoding="utf-8",
    )
    return config


def test_short_term_memory_keeps_sliding_window():
    memory = ShortTermChatMemory(max_turns=4)
    for index in range(8):
        memory.add("user", f"turn {index}")

    assert len(memory.turns) == 4
    assert memory.turns[0].content == "turn 4"
    assert "turn 7" in memory.context_lines()


def test_user_preference_memory_extracts_and_merges_rules(tmp_path):
    memory = UserPreferenceMemory(root=tmp_path / "memory")

    changed = memory.extract_and_save("u1", "我叫小明，以后默认用中文，报告风格详细但结论先行")
    context = memory.render_context("u1")

    assert {item["key"] for item in changed} >= {"name", "default_requirement", "report_style", "language"}
    assert "小明" in context
    assert "zh-CN" in context


def test_long_term_memory_recall_filters_symbol_and_scores(tmp_path):
    memory = LongTermChatMemory(root=tmp_path / "memory")
    memory.add("u1", "AAPL 2025Q4 revenue margin discussion", session_id="s1", symbol="AAPL", period="2025Q4")
    memory.add("u1", "600519 2025Q4 baijiu revenue discussion", session_id="s1", symbol="600519.SS", period="2025Q4")

    hits = memory.recall("u1", "AAPL revenue", symbol="AAPL", period="2025Q4")

    assert hits
    assert hits[0]["symbol"] == "AAPL"
    assert "evidence_id" not in hits[0]


def test_agent_chat_service_falls_back_without_api_key_and_marks_memory_boundary(tmp_path):
    service = AgentChatService(
        config_path=str(_model_config(tmp_path)),
        memory_root=tmp_path / "memory",
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
    )

    response = service.handle_chat(
        message="我喜欢简洁回答，请根据证据说明 AMD 研报还缺什么",
        session_id="s1",
        user_id="u1",
        symbol="AMD",
        period="2025Q4",
        memory_enabled=True,
    )

    assert response["mode"] in {"chat", "rag"}
    assert response["answer"]
    assert response["memory_used"]["enabled"] is True
    assert "never substitutes" in response["memory_used"]["boundary"]
    assert response["tool_trace"]


def test_agent_chat_routes_chinese_report_and_review_terms(tmp_path):
    service = AgentChatService(
        config_path=str(_model_config(tmp_path)),
        memory_root=tmp_path / "memory",
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
    )

    assert service._route("请生成贵州茅台最新财报研报", allow_report_run=True)["mode"] == "report_run"
    assert service._route("generate 600519 latest company report", allow_report_run=True)["mode"] == "report_run"
    assert service._route("复盘一下报告引用和评测问题", allow_report_run=True)["mode"] == "rag"
