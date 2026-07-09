from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.db.models import Company, Document, EvidenceItem
from src.services.report_task_service import ReportTaskService


class CountingOrchestrator:
    calls = 0

    def __init__(self, output_dir, report_dir, **kwargs):
        self.output_dir = output_dir
        self.report_dir = report_dir

    def run(self, **kwargs):
        type(self).calls += 1
        return {"verification_passed": True, "quality_score": 0.9}


def passing_quality_runner(output_dir, report_dir, **kwargs):
    return {
        "quality_report": {"objective_pass": True, "total_score": 0.92},
        "llm_quality_review": {"llm_review_pass": True, "total_score": 0.9, "model_status": "test"},
        "delivery_gate": {"delivery_pass": True, "objective_pass": True, "llm_review_pass": True},
        "top_quality_issues": [],
    }


def build_client(tmp_path):
    CountingOrchestrator.calls = 0
    service = ReportTaskService(
        database_url=f"sqlite:///{tmp_path / 'tasks.db'}",
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
        orchestrator_factory=CountingOrchestrator,
        quality_runner=passing_quality_runner,
    )
    app = create_fastapi_app(
        output_dir=str(tmp_path / "legacy_outputs"),
        report_dir=str(tmp_path / "legacy_reports"),
        memory_root=str(tmp_path / "legacy_memory"),
        report_task_service=service,
    )
    return service, TestClient(app)


def seed_official_evidence(service, *, task_id: str | None = None):
    with service.session() as session:
        company = Company(name="NVIDIA Corporation", symbol="NVDA", market="US")
        session.add(company)
        session.flush()
        document = Document(
            company_id=company.id,
            batch_id=task_id or "batch-nvda-fy2024",
            title="NVIDIA FY2024 Form 10-K",
            doc_type="10-K",
            report_period="FY2024",
            source_url="https://example.com/nvda-10k",
            parse_status="parsed",
        )
        session.add(document)
        session.flush()
        session.add(
            EvidenceItem(
                evidence_id=f"ev_gate_{task_id or 'official'}",
                company_id=company.id,
                document_id=document.id,
                source_type="sec_edgar",
                trust_level="official",
                title="FY2024 revenue evidence",
                content="NVIDIA revenue increased in fiscal 2024.",
                metadata_json={"period": "FY2024", "task_id": task_id} if task_id else {"period": "FY2024"},
            )
        )
        session.commit()


def test_enforced_evidence_gate_blocks_generation_without_evidence(tmp_path):
    _, client = build_client(tmp_path)

    with client:
        response = client.post(
            "/api/report-tasks",
            json={
                "task_id": "task-gate-block",
                "symbol": "NVDA",
                "period": "FY2024",
                "company_name": "NVIDIA",
                "enforce_evidence_gate": True,
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "quality_failed"
    assert body["current_stage"] == "evidence_gate_failed"
    assert CountingOrchestrator.calls == 0
    gate = body["metadata"]["pre_generation_evidence_gate"]
    assert gate["blocked"] is True
    assert gate["coverage"]["evidence_ready"] is False
    assert any(reason["type"] == "no_evidence" for reason in gate["blocking_reasons"])
    assert body["events"][-1]["stage"] == "evidence_gate"
    assert body["events"][-1]["status"] == "failed"


def test_enforced_evidence_gate_allows_generation_with_required_official_source(tmp_path):
    service, client = build_client(tmp_path)
    seed_official_evidence(service)

    with client:
        response = client.post(
            "/api/report-tasks",
            json={
                "task_id": "task-gate-pass",
                "symbol": "NVDA",
                "period": "FY2024",
                "company_name": "NVIDIA",
                "enforce_evidence_gate": True,
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "completed"
    assert CountingOrchestrator.calls == 1
    gate = body["metadata"]["pre_generation_evidence_gate"]
    assert gate["blocked"] is False
    assert gate["status"] == "success"
    assert gate["coverage"]["quality_ready"] is True
    assert gate["coverage"]["returned_sources"] == ["sec_edgar"]


def test_default_evidence_gate_records_warning_without_blocking_legacy_fast_task(tmp_path):
    _, client = build_client(tmp_path)

    with client:
        response = client.post(
            "/api/report-tasks",
            json={"task_id": "task-gate-warning", "symbol": "AAPL", "period": "FY2024"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "completed"
    assert CountingOrchestrator.calls == 1
    gate = body["metadata"]["pre_generation_evidence_gate"]
    assert gate["status"] == "warning"
    assert gate["blocked"] is False
    assert gate["coverage"]["evidence_ready"] is False
