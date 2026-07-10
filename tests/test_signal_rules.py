from src.db.models import Company, EvidenceItem, FinancialFact
from src.services.investment_signal_service import InvestmentSignalService


def test_signal_rules_generate_financial_research_signals(temp_db_engine):
    from sqlalchemy.orm import Session, sessionmaker

    session_factory = sessionmaker(bind=temp_db_engine, autoflush=False, expire_on_commit=False, class_=Session)
    temp_db_session = session_factory()
    company = Company(name="苹果公司", symbol="AAPL", market="US")
    evidence = EvidenceItem(
        evidence_id="ev-aapl-facts",
        company=company,
        source_type="sec_edgar",
        trust_level="primary",
        title="AAPL FY2024 10-K",
        content="Revenue, margin and cash flow facts.",
        metadata_json={"period": "FY2024"},
    )
    temp_db_session.add_all([company, evidence])
    temp_db_session.flush()
    temp_db_session.add_all(
        [
            FinancialFact(
                company_id=company.id,
                evidence_item_id=evidence.id,
                metric_name="营业收入",
                metric_type="money",
                value=100.0,
                currency="USD",
                unit="million",
                period="FY2022",
                confidence=0.9,
            ),
            FinancialFact(
                company_id=company.id,
                evidence_item_id=evidence.id,
                metric_name="营业收入",
                metric_type="money",
                value=104.0,
                currency="USD",
                unit="million",
                period="FY2023",
                confidence=0.9,
            ),
            FinancialFact(
                company_id=company.id,
                evidence_item_id=evidence.id,
                metric_name="营业收入",
                metric_type="money",
                value=115.0,
                currency="USD",
                unit="million",
                period="FY2024",
                confidence=0.9,
            ),
            FinancialFact(
                company_id=company.id,
                evidence_item_id=evidence.id,
                metric_name="毛利率",
                metric_type="ratio",
                value=46.0,
                unit="%",
                period="FY2023",
                confidence=0.88,
            ),
            FinancialFact(
                company_id=company.id,
                evidence_item_id=evidence.id,
                metric_name="毛利率",
                metric_type="ratio",
                value=42.5,
                unit="%",
                period="FY2024",
                confidence=0.88,
            ),
            FinancialFact(
                company_id=company.id,
                evidence_item_id=evidence.id,
                metric_name="净利润",
                metric_type="money",
                value=12.0,
                currency="USD",
                unit="million",
                period="FY2024",
                confidence=0.86,
            ),
            FinancialFact(
                company_id=company.id,
                evidence_item_id=evidence.id,
                metric_name="经营现金流",
                metric_type="money",
                value=-3.0,
                currency="USD",
                unit="million",
                period="FY2024",
                confidence=0.86,
            ),
        ]
    )
    temp_db_session.commit()
    temp_db_session.close()

    service = InvestmentSignalService(session_factory=session_factory)
    result = service.generate_signals(company="AAPL", period="FY2024")
    types = {item["signal_type"] for item in result["items"]}

    assert {"margin_decline", "cashflow_gap", "revenue_growth_acceleration", "valuation_blocked"}.issubset(types)
    assert "official_source_missing" not in types
    assert all("不构成投资建议" in item["metadata"]["boundary"] for item in result["items"])
