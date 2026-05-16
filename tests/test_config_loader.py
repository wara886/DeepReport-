from src.utils.config import load_config


def test_load_local_debug_yaml():
    config = load_config("configs/local_debug.yaml")
    assert config["runtime"]["mode"] == "local_debug"
    assert config["generation"]["backend"] == "mock"
    assert config["project"]["name"] == "open-deepreport-plus"


def test_app_yaml_contains_durable_memory_defaults():
    config = load_config("configs/app.yaml")
    durable = config["memory"]["durable"]
    assert durable["enabled"] is False
    assert durable["root"] == "memory"
    assert durable["max_context_chars"] > 0
    assert durable["context_scope"] == "planner_router"
    chat = config["memory"]["chat"]
    assert chat["enabled"] is False
    assert chat["root"] == "memory/chat"
    assert chat["boundary"] == "context_only_not_evidence"
