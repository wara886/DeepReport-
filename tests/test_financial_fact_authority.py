"""Test FinancialFact authority level assignment and formal usage constraints."""

from sqlalchemy import select

from src.db.init_db import init_db
from src.db.models import EvidenceItem, FinancialFact
from src.services.financial_fact_service import FinancialFactService
from src.services.report_task_service import ReportTaskService


def test_financial_fact_authority_assigned_from_official_evidence(tmp_path):
    """Official filing evidence → authority_level = primary_official, usable_for_formal_report = True."""
    engine = init_db(f"sqlite:///{tmp_path / 'fact_authority.db'}")
    report_service = ReportTaskService(
        engine=engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    with report_service.session() as session:
        session.add(
            EvidenceItem(
                evidence_id="ev-official-001",
                source_type="filing",
                trust_level="high",
                title="AAPL 10-K FY2024",
                content="Revenue 391035 million USD.",
                source_url="https://www.sec.gov/example",
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
            "evidence_id": "ev-official-001",
        }
    )

    assert fact["authority_level"] == "primary_official"
    assert fact["usable_for_formal_report"] is True
    assert fact["fact_status"] == "verified"


def test_financial_fact_authority_from_market_data_is_restricted(tmp_path):
    """Market API evidence → authority_level = market_data, not usable for formal reports."""
    engine = init_db(f"sqlite:///{tmp_path / 'fact_market.db'}")
    report_service = ReportTaskService(
        engine=engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    with report_service.session() as session:
        session.add(
            EvidenceItem(
                evidence_id="ev-market-001",
                source_type="market_api",
                trust_level="medium",
                title="AAPL Yahoo Finance snapshot",
                content="Revenue 391035 million USD.",
                source_url="https://finance.yahoo.com/example",
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
            "evidence_id": "ev-market-001",
        }
    )

    assert fact["authority_level"] == "market_data"
    assert fact["usable_for_formal_report"] is False
    assert fact["fact_status"] == "needs_review"


def test_financial_fact_without_evidence_is_llm_inferred(tmp_path):
    """No evidence link → authority_level = llm_inferred, not usable for formal reports."""
    engine = init_db(f"sqlite:///{tmp_path / 'fact_no_ev.db'}")
    report_service = ReportTaskService(
        engine=engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    service = FinancialFactService(session_factory=report_service.session)
    fact = service.import_fact(
        {
            "metric_name": "Revenue",
            "value": 391035,
            "period": "FY2024",
            "symbol": "AAPL",
            "currency": "USD",
            "unit": "million",
        }
    )

    assert fact["authority_level"] == "llm_inferred"
    assert fact["usable_for_formal_report"] is False


def test_manually_approved_fact_can_be_formal(tmp_path):
    """Manual approval overrides authority to usable for formal reports."""
    engine = init_db(f"sqlite:///{tmp_path / 'fact_manual_approve.db'}")
    report_service = ReportTaskService(
        engine=engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    service = FinancialFactService(session_factory=report_service.session)
    fact = service.import_fact(
        {
            "metric_name": "Revenue",
            "value": 391035,
            "period": "FY2024",
            "symbol": "AAPL",
            "currency": "USD",
            "unit": "million",
            "authority_level": "manual_approved",
            "fact_status": "verified",
            "usable_for_formal_report": True,
        }
    )

    assert fact["authority_level"] == "manual_approved"
    assert fact["usable_for_formal_report"] is True
    assert fact["fact_status"] == "verified"


def test_explicit_authority_overrides_auto_detection(tmp_path):
    """Explicitly provided authority_level takes precedence over automatic detection."""
    engine = init_db(f"sqlite:///{tmp_path / 'fact_explicit.db'}")
    report_service = ReportTaskService(
        engine=engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    with report_service.session() as session:
        session.add(
            EvidenceItem(
                evidence_id="ev-explicit-001",
                source_type="market_api",
                trust_level="medium",
                title="AAPL snapshot",
                content="Revenue 391035 million USD.",
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
            "evidence_id": "ev-explicit-001",
            "authority_level": "secondary_structured",
            "usable_for_formal_report": False,
        }
    )

    assert fact["authority_level"] == "secondary_structured"
    assert fact["usable_for_formal_report"] is False


def test_secondary_cninfo_is_market_data_not_primary(tmp_path):
    """EastMoney / cninfo data is third-party structured, not primary."""
    engine = init_db(f"sqlite:///{tmp_path / 'fact_cninfo.db'}")
    report_service = ReportTaskService(
        engine=engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    with report_service.session() as session:
        session.add(
            EvidenceItem(
                evidence_id="ev-cninfo-001",
                source_type="eastmoney_financials",
                trust_level="medium",
                title="600519 Eastmoney financial table",
                content="营收 1200 亿元。",
                source_url="https://data.eastmoney.com/bbsj/600519.html",
            )
        )
        session.commit()

    service = FinancialFactService(session_factory=report_service.session)
    fact = service.import_fact(
        {
            "metric_name": "营收",
            "value": 1200,
            "period": "FY2025",
            "symbol": "600519.SS",
            "currency": "CNY",
            "unit": "亿",
            "evidence_id": "ev-cninfo-001",
        }
    )

    assert fact["authority_level"] == "market_data"
    assert fact["usable_for_formal_report"] is False


def test_delivery_gate_blocks_formal_report_with_market_data_facts(tmp_path):
    """Delivery readiness rejects formal delivery if core financial facts lack authority."""
    from sqlalchemy.orm import selectinload
    from src.db.models import ReportTask, ReportClaim
    from src.runtime.report_run_state import build_report_run_state

    engine = init_db(f"sqlite:///{tmp_path / 'fact_delivery.db'}")
    report_service = ReportTaskService(
        engine=engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )

    with report_service.session() as session:
        task = ReportTask(
            task_id="task-fact-delivery-authority",
            symbol="AAPL",
            period="FY2024",
            report_type="equity_research",
            status="generation_completed",
            current_stage="generation_completed",
            metadata_json={
                "report_runtime": {"lifecycle_status": "generation_completed"},
                "quality_result": {
                    "delivery_gate": {
                        "delivery_pass": False,
                        "review_required": False,
                    }
                },
            },
        )
        session.add(task)
        session.flush()

        session.add(
            EvidenceItem(
                evidence_id="ev-delivery-test",
                source_type="market_api",
                trust_level="medium",
                title="Market data",
                content="Revenue data",
            )
        )
        session.flush()

        session.add(
            FinancialFact(
                company_id=None,
                evidence_item_id=None,
                metric_name="Revenue",
                metric_type="money",
                value=391035,
                currency="USD",
                unit="million",
                scale="million",
                period="FY2024",
                authority_level="market_data",
                fact_status="needs_review",
                usable_for_formal_report=False,
            )
        )
        session.flush()
        task = session.scalar(
            select(ReportTask)
            .where(ReportTask.task_id == "task-fact-delivery-authority")
            .options(selectinload(ReportTask.claims), selectinload(ReportTask.artifacts))
        )

    run_state = build_report_run_state(task)
    delivery = run_state["delivery_readiness"]
    export = run_state["export_readiness"]

    assert delivery["can_export_formal_package"] is False
    assert export["can_export_formal_package"] is False
