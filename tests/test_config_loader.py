from src.utils.config import load_config


def test_load_local_debug_yaml():
    config = load_config("configs/local_debug.yaml")
    assert config["runtime"]["mode"] == "local_debug"
    assert config["generation"]["backend"] == "mock"
    assert config["project"]["name"] == "open-deepreport-plus"

