import pytest

from src.db.init_db import init_db
from src.services.financial_fact_service import FinancialFactConflict, FinancialFactService
from src.services.report_task_service import ReportTaskService


def build_service(tmp_path):
    engine = init_db(f"sqlite:///{tmp_path / 'money_fact.db'}")
    report_service = ReportTaskService(
        engine=engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    return FinancialFactService(session_factory=report_service.session)


def test_money_fact_requires_currency_and_unit(tmp_path):
    service = build_service(tmp_path)

    with pytest.raises(FinancialFactConflict):
        service.import_fact({"metric_name": "营业收入", "value": 100, "period": "FY2024", "symbol": "AAPL"})

    fact = service.import_fact(
        {
            "metric_name": "营业收入",
            "value": 391035,
            "period": "FY2024",
            "symbol": "AAPL",
            "currency": "USD",
            "unit": "million",
        }
    )

    assert fact["metric_type"] == "money"
    assert fact["currency"] == "USD"
    assert fact["unit"] == "million"
