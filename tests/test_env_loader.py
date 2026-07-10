import os

from src.utils.env import load_env_files


def test_env_loader_can_fallback_to_legacy_deepreport_env(tmp_path, monkeypatch):
    project = tmp_path / "DeepReport-fin-workbench-v2"
    legacy = tmp_path / "DeepReport-wara886"
    configs = project / "configs"
    configs.mkdir(parents=True)
    legacy.mkdir()
    (configs / "data_sources.yaml").write_text("search: {}\n", encoding="utf-8")
    (project / ".env").write_text("DEEPSEEK_API_KEY=current\n", encoding="utf-8")
    (legacy / ".env").write_text("TAVILY_API_KEY=legacy-tavily\nDEEPSEEK_API_KEY=legacy\n", encoding="utf-8")
    monkeypatch.chdir(project)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    load_env_files(config_path=configs / "data_sources.yaml")

    assert os.environ["TAVILY_API_KEY"] == "legacy-tavily"
    assert os.environ["DEEPSEEK_API_KEY"] == "current"
