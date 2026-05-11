from src.models.model_adapter import ModelAdapter, extract_json_object


def test_model_adapter_loads_deepseek_config_from_env_file(tmp_path, monkeypatch):
    for key in [
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "DEEPSEEK_MODEL",
        "DEEPSEEK_MAX_TOKENS",
        "DEEPSEEK_TEMPERATURE",
    ]:
        monkeypatch.delenv(key, raising=False)

    config_path = tmp_path / "model_backends.yaml"
    env_path = tmp_path / ".env"
    config_path.write_text(
        """
agent_model:
  provider: deepseek
  model_name: deepseek-v4-flash
  model_name_env: DEEPSEEK_MODEL
  base_url: https://api.deepseek.com
  base_url_env: DEEPSEEK_BASE_URL
  api_key: ""
  api_key_env: DEEPSEEK_API_KEY
  max_tokens: 4096
  max_tokens_env: DEEPSEEK_MAX_TOKENS
  temperature: 0.2
  temperature_env: DEEPSEEK_TEMPERATURE
  timeout: 9
  retry: 0
""".strip(),
        encoding="utf-8",
    )
    env_path.write_text(
        "\n".join(
            [
                "DEEPSEEK_API_KEY=sk-test",
                "DEEPSEEK_BASE_URL=https://api.deepseek.com/v1",
                "DEEPSEEK_MODEL=deepseek-v4-pro",
                "DEEPSEEK_MAX_TOKENS=1234",
                "DEEPSEEK_TEMPERATURE=0.1",
            ]
        ),
        encoding="utf-8",
    )

    adapter = ModelAdapter.from_config(config_path=config_path, env_path=env_path)

    assert adapter.provider == "deepseek"
    assert adapter.api_key == "sk-test"
    assert adapter.base_url == "https://api.deepseek.com/v1"
    assert adapter.endpoint_url == "https://api.deepseek.com/v1/chat/completions"
    assert adapter.model_name == "deepseek-v4-pro"
    assert adapter.max_tokens == 1234
    assert adapter.temperature == 0.1
    assert adapter.timeout == 9


def test_model_adapter_missing_key_returns_clear_error():
    adapter = ModelAdapter(
        provider="deepseek",
        model_name="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        api_key="",
    )

    response = adapter.generate("hello")

    assert response.success is False
    assert "DEEPSEEK_API_KEY" in response.error


def test_model_adapter_endpoint_keeps_full_chat_completion_url():
    adapter = ModelAdapter(
        provider="deepseek",
        model_name="deepseek-v4-flash",
        base_url="https://api.deepseek.com/chat/completions",
        api_key="sk-test",
    )

    assert adapter.endpoint_url == "https://api.deepseek.com/chat/completions"


def test_extract_json_object_from_fenced_response():
    parsed = extract_json_object(
        """
```json
{"tasks": [{"task_id": "task_001"}]}
```
""".strip()
    )

    assert parsed == {"tasks": [{"task_id": "task_001"}]}
