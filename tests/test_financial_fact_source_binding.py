from src.db.init_db import init_db
from src.db.models import EvidenceItem
from src.services.financial_fact_service import FinancialFactService
from src.services.report_task_service import ReportTaskService


def test_financial_fact_binds_to_evidence_source(tmp_path):
    engine = init_db(f"sqlite:///{tmp_path / 'fact_source.db'}")
    report_service = ReportTaskService(
        engine=engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    with report_service.session() as session:
        session.add(
            EvidenceItem(
                evidence_id="ev-fact-001",
                source_type="official_filing",
                trust_level="official",
                title="AAPL FY2024 10-K",
                content="Revenue was 391035 million USD.",
                source_url="https://www.sec.gov/example",
                page_no=42,
            )
        )
        session.commit()
    service = FinancialFactService(session_factory=report_service.session)

    fact = service.import_fact(
        {
            "metric_name": "Revenue",
            "value": 391035,
            "period": "FY2024",
            "symbol": "AAPL",
            "currency": "USD",
            "unit": "million",
            "evidence_id": "ev-fact-001",
            "confidence": 0.95,
        }
    )
    detail = service.get_fact(fact["id"])

    assert detail["evidence"]["evidence_id"] == "ev-fact-001"
    assert detail["source_url"] == "https://www.sec.gov/example"
    assert detail["confidence"] == 0.95
