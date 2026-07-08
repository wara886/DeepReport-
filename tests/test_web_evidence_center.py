from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.db.models import EvidenceItem
from src.services.report_task_service import ReportTaskService


def test_workbench_exposes_evidence_center_contract(temp_db_engine, tmp_path):
    service = ReportTaskService(
        engine=temp_db_engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    with service.session() as session:
        session.add(
            EvidenceItem(
                evidence_id="ev_web_contract",
                content="Evidence visible from the workbench.",
                source_type="sec_edgar",
                trust_level="official",
            )
        )
        session.commit()
    app = create_fastapi_app(
        output_dir=str(tmp_path / "legacy_outputs"),
        report_dir=str(tmp_path / "legacy_reports"),
        memory_root=str(tmp_path / "legacy_memory"),
        report_task_service=service,
    )

    with TestClient(app) as client:
        page = client.get("/workbench")
        evidence = client.get("/api/evidence")

    assert page.status_code == 200
    html = page.text
    assert "证据库" in html
    assert 'getJson("/api/evidence" + suffix)' in html
    assert 'getJson(`/api/evidence/${encodeURIComponent(evidenceId)}`)' in html
    assert "主张复核" in html
    assert "文档处理中心" in html
    assert "导出中心" in html
    assert "投资线索" in html
    assert "生成规则线索" in html
    assert "实体库" in html
    assert "关系图谱" in html
    assert "沉淀到实体库" in html
    assert 'postJson("/api/entities/extract-from-evidence"' in html
    assert 'getJson("/api/entities" + suffix)' in html
    assert 'getJson("/api/entity-relations" + suffix)' in html
    assert 'getJson("/api/graph/summary?limit=120")' in html
    assert 'getJson("/api/investment-signals" + suffix)' in html
    assert 'postJson("/api/investment-signals/generate"' in html
    assert 'add-to-task' in html
    assert evidence.status_code == 200
    assert evidence.json()["items"][0]["evidence_id"] == "ev_web_contract"
