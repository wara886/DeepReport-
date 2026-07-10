from src.db.init_db import init_db
from src.services.promptops_service import PromptOpsService
from src.services.report_task_service import ReportTaskService


def build_service(tmp_path):
    engine = init_db(f"sqlite:///{tmp_path / 'promptops_active.db'}")
    report_service = ReportTaskService(
        engine=engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    return PromptOpsService(session_factory=report_service.session)


def test_promptops_active_version_resolution_uses_latest_active_version(tmp_path):
    service = build_service(tmp_path)
    template = service.create_template(
        {
            "prompt_key": "claim_verifier",
            "name": "主张校验",
            "module": "verifier",
            "content": "v1 {{claim}}",
            "variables": ["claim"],
        }
    )
    v2 = service.add_version("claim_verifier", {"content": "v2 {{claim}}", "changelog": "改进输出格式", "is_active": True})
    active = service.resolve_active_version("claim_verifier")

    assert template["active_version"] == 1
    assert v2["version"] == 2
    assert active["version"] == 2
    assert active["content"] == "v2 {{claim}}"
    assert active["template"]["prompt_key"] == "claim_verifier"
