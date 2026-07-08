from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from src.app.api_fastapi import create_fastapi_app
from src.db.models import Company, EvidenceItem, FinancialFact
from src.services.report_task_service import ReportTaskService


def build_client(tmp_path):
    service = ReportTaskService(
        database_url=f"sqlite:///{tmp_path / 'signals_api.db'}",
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    app = create_fastapi_app(
        output_dir=str(tmp_path / "legacy_outputs"),
        report_dir=str(tmp_path / "legacy_reports"),
        memory_root=str(tmp_path / "legacy_memory"),
        report_task_service=service,
    )
    return TestClient(app), service


def seed_margin_fact(service):
    session_factory = sessionmaker(bind=service._engine, autoflush=False, expire_on_commit=False, class_=Session)
    with session_factory() as session:
        company = Company(name="英伟达", symbol="NVDA", market="US")
        evidence = EvidenceItem(
            evidence_id="ev-nvda-margin",
            company=company,
            source_type="sec_edgar",
            trust_level="primary",
            title="NVDA annual report",
            content="Gross margin declined.",
            metadata_json={"period": "FY2024"},
        )
        session.add_all([company, evidence])
        session.flush()
        session.add_all(
            [
                FinancialFact(
                    company_id=company.id,
                    evidence_item_id=evidence.id,
                    metric_name="毛利率",
                    metric_type="ratio",
                    value=57.0,
                    unit="%",
                    period="FY2023",
                    confidence=0.9,
                ),
                FinancialFact(
                    company_id=company.id,
                    evidence_item_id=evidence.id,
                    metric_name="毛利率",
                    metric_type="ratio",
                    value=53.0,
                    unit="%",
                    period="FY2024",
                    confidence=0.9,
                ),
            ]
        )
        session.commit()


def test_signal_api_generates_and_returns_evidence_binding(tmp_path):
    with build_client(tmp_path)[0] as client:
        service = client.app.state.report_task_service
        service.session().close()
        seed_margin_fact(service)
        generated = client.post("/api/investment-signals/generate", json={"company": "NVDA", "period": "FY2024"})
        listed = client.get("/api/investment-signals", params={"company": "NVDA"})
        detail = client.get(f"/api/investment-signals/{generated.json()['items'][0]['id']}")

    assert generated.status_code == 201
    assert generated.json()["generated"] >= 1
    assert listed.status_code == 200
    signal = next(item for item in listed.json()["items"] if item["signal_type"] == "margin_decline")
    assert signal["signal_type"] == "margin_decline"
    assert signal["evidence"]["evidence_id"] == "ev-nvda-margin"
    assert detail.status_code == 200
    assert detail.json()["source_fact"]["metric_name"] == "毛利率"
