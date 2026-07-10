from fastapi.testclient import TestClient
import json

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


class WeakArtifactOrchestrator:
    calls = 0

    def __init__(self, output_dir, report_dir, **kwargs):
        self.output_dir = output_dir
        self.report_dir = report_dir

    def run(self, **kwargs):
        type(self).calls += 1
        from pathlib import Path

        output_dir = Path(self.output_dir)
        report_dir = Path(self.report_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        report_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "evidence.json").write_text(
            json.dumps(
                [
                    {
                        "evidence_id": "ev_local_profile",
                        "source_type": "company_profile",
                        "trust_level": "medium",
                        "title": "Local company profile",
                        "content": "NVIDIA is a semiconductor company.",
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (output_dir / "claims.json").write_text(
            json.dumps(
                [
                    {
                        "claim_id": "cl_local_summary",
                        "section_name": "执行摘要",
                        "claim_text": "NVIDIA has an investable AI business profile.",
                        "evidence_ids": ["ev_local_profile"],
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (report_dir / "report.md").write_text(
            "# NVDA FY2024 公司研报\n\n"
            "## 执行摘要\n本节暂不展开详细分析（evidence_not_available）。\n\n"
            "## 风险评估\n待官方风险章节进一步校验。\n\n"
            "## 投资结论\n审慎观察。\n",
            encoding="utf-8",
        )
        (report_dir / "report.html").write_text("<html><body><h1>NVDA FY2024 公司研报</h1></body></html>", encoding="utf-8")
        return {"verification_passed": True, "quality_score": 0.5}


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


def build_client_with_orchestrator(tmp_path, orchestrator_factory):
    service = ReportTaskService(
        database_url=f"sqlite:///{tmp_path / 'tasks.db'}",
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
        orchestrator_factory=orchestrator_factory,
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
    seed_task_evidence(service, task_id=task_id, source_type="sec_edgar", trust_level="official")


def seed_task_evidence(
    service,
    *,
    task_id: str | None = None,
    source_type: str = "sec_edgar",
    trust_level: str = "official",
):
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
                evidence_id=f"ev_gate_{source_type}_{task_id or 'source'}",
                company_id=company.id,
                document_id=document.id,
                source_type=source_type,
                trust_level=trust_level,
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
    assert gate["draft_ready"] is False
    assert gate["delivery_ready"] is False
    assert gate["delivery_blocked_reasons"]
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
    assert gate["draft_ready"] is True
    assert gate["delivery_ready"] is True
    assert gate["delivery_blocked_reasons"] == []
    assert gate["status"] == "success"
    assert gate["coverage"]["quality_ready"] is True
    assert gate["coverage"]["returned_sources"] == ["sec_edgar"]


def test_task_official_db_evidence_is_merged_into_report_artifacts_before_quality_gate(tmp_path):
    WeakArtifactOrchestrator.calls = 0
    service, client = build_client_with_orchestrator(tmp_path, WeakArtifactOrchestrator)
    seed_official_evidence(service)

    with client:
        response = client.post(
            "/api/report-tasks",
            json={
                "task_id": "task-official-artifact-merge",
                "symbol": "NVDA",
                "period": "FY2024",
                "company_name": "NVIDIA",
                "enforce_evidence_gate": True,
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "completed"
    assert WeakArtifactOrchestrator.calls == 1

    output_dir = tmp_path / "outputs" / "runs" / "task-official-artifact-merge" / "outputs"
    report_dir = tmp_path / "reports" / "runs" / "task-official-artifact-merge" / "reports"
    evidence = json.loads((output_dir / "evidence.json").read_text(encoding="utf-8"))
    claims = json.loads((output_dir / "claims.json").read_text(encoding="utf-8"))
    citations = json.loads((output_dir / "citations.json").read_text(encoding="utf-8"))
    report_md = (report_dir / "report.md").read_text(encoding="utf-8")
    report_html = (report_dir / "report.html").read_text(encoding="utf-8")

    official_id = "ev_gate_sec_edgar_source"
    assert any(item["evidence_id"] == official_id and item["source_authority"] == "official" for item in evidence)
    assert any(official_id in claim.get("evidence_ids", []) for claim in claims)
    assert any(item["evidence_id"] == official_id and item["used_in_report"] is True for item in citations)
    assert official_id in report_md
    assert "本节暂不展开详细分析" not in report_md
    assert "中性 / 审慎观察" in report_md
    assert "正式投资建议仍缺少完整预测模型" in report_md
    assert "参考来源" in report_html
    assert "FY2024 revenue evidence" in report_html


def test_enforced_evidence_gate_blocks_delivery_when_official_source_is_missing(tmp_path):
    service, client = build_client(tmp_path)
    seed_task_evidence(service, source_type="local_evidence", trust_level="primary")

    with client:
        response = client.post(
            "/api/report-tasks",
            json={
                "task_id": "task-gate-official-gap",
                "symbol": "NVDA",
                "period": "FY2024",
                "company_name": "NVIDIA",
                "enforce_evidence_gate": True,
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "quality_failed"
    assert CountingOrchestrator.calls == 0
    gate = body["metadata"]["pre_generation_evidence_gate"]
    assert gate["blocked"] is True
    assert gate["draft_ready"] is False
    assert gate["delivery_ready"] is False
    assert gate["coverage"]["evidence_ready"] is True
    assert gate["coverage"]["quality_ready"] is False
    assert gate["coverage"]["returned_sources"] == ["local_evidence"]
    assert gate["coverage"]["missing_sources"] == ["sec_edgar"]
    assert any("美国证监会披露" in reason["description"] for reason in gate["delivery_blocked_reasons"])


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
    assert gate["draft_ready"] is True
    assert gate["delivery_ready"] is False
    assert any(reason["type"] == "no_evidence" for reason in gate["delivery_blocked_reasons"])
    assert gate["coverage"]["evidence_ready"] is False
