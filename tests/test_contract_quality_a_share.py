from src.report.contract_builder import build_report_section_contracts


def test_peer_compare_target_only_is_gap_not_supported():
    contracts = build_report_section_contracts(
        state={"symbol": "600519.SS", "period": "2026Q1", "research_blackboard": {}},
        evidence_records=[],
        analysis_artifacts={
            "peer_rows": [
                {
                    "symbol": "600519.SS",
                    "company_name": "Kweichow Moutai",
                    "sector": "Consumer Defensive",
                    "industry": "Beverages",
                    "is_target": True,
                }
            ]
        },
        section_dossiers={},
        citations=[],
    )

    peer = contracts.get("peer_compare")
    assert peer is not None
    assert peer.status == "gap"
    assert "peer_only_target_row" in peer.blocked_reasons


def test_core_contract_sections_allow_llm_rewrite():
    contracts = build_report_section_contracts(
        state={"symbol": "600519.SS", "period": "2026Q1", "research_blackboard": {}},
        evidence_records=[],
        analysis_artifacts={
            "financial_metrics": {"metrics": [{"metric_key": "revenue", "value": 1}]},
            "valuation_model": {"valuation_status": "rough_observation_only"},
        },
        section_dossiers={},
        citations=[],
    )

    for key in [
        "three_statement_summary",
        "financial_analysis",
        "peer_compare",
        "valuation",
        "valuation_sensitivity",
        "investment_conclusion",
    ]:
        section = contracts.get(key)
        assert section is not None
        assert section.render_policy.get("allow_llm_rewrite") is True


def test_three_statement_contract_inherits_structured_evidence_and_renders_table():
    evidence_id = "600000_FY2025_eastmoney_financials_income_x"
    contracts = build_report_section_contracts(
        state={
            "symbol": "600000.SS",
            "period": "FY2025",
            "claims": [{"claim_id": "cl_1", "evidence_ids": [evidence_id]}],
            "research_blackboard": {},
        },
        evidence_records=[],
        analysis_artifacts={
            "financial_metrics": {
                "metrics": [
                    {"metric_name": "revenue", "value": 10000000000, "source_evidence_id": evidence_id},
                    {"metric_name": "net_income", "value": 2000000000, "source_evidence_id": evidence_id},
                    {"metric_name": "total_assets", "value": 30000000000, "source_evidence_id": "ev_balance"},
                ]
            },
            "tables": [
                {
                    "table_type": "income_statement",
                    "source_evidence_id": evidence_id,
                    "rows": [
                        {"line_item": "收入", "value": 10000000000, "period": "FY2025", "source_evidence_id": evidence_id, "source_type": "eastmoney_financials"},
                        {"line_item": "净利润", "value": 2000000000, "period": "FY2025", "source_evidence_id": evidence_id, "source_type": "eastmoney_financials"},
                    ],
                },
                {
                    "table_type": "balance_sheet",
                    "source_evidence_id": "ev_balance",
                    "rows": [
                        {"line_item": "total_assets", "value": 30000000000, "period": "FY2025", "source_evidence_id": "ev_balance", "source_type": "eastmoney_financials"},
                        {"line_item": "total_liabilities", "value": 5000000000, "period": "FY2025", "source_evidence_id": "ev_balance", "source_type": "eastmoney_financials"},
                        {"line_item": "equity", "value": 25000000000, "period": "FY2025", "source_evidence_id": "ev_balance", "source_type": "eastmoney_financials"},
                    ],
                },
                {
                    "table_type": "cash_flow_statement",
                    "source_evidence_id": "ev_cash",
                    "rows": [
                        {"line_item": "operating_cash_flow", "value": 3000000000, "period": "FY2025", "source_evidence_id": "ev_cash", "source_type": "eastmoney_financials"},
                    ],
                },
            ],
        },
        section_dossiers={},
        citations=[],
    )

    section = contracts.get("three_statement_summary")
    assert section is not None
    assert section.status == "supported"
    assert evidence_id in section.citation_evidence_ids
    assert "ev_balance" in section.citation_evidence_ids
    assert "| 指标 | 金额 | 期间 | 来源 |" in section.deterministic_text
