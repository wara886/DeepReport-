from scripts.run_fastapi_server import dependency_preflight


def test_server_dependency_preflight_passes_for_test_environment():
    assert dependency_preflight() == []
