from src.agents.browser_agent import filter_evidence_for_target
from src.db.models import Company, EvidenceItem, ReportTask
from src.services.report_task_service import _artifact_record_from_evidence, _evidence_matches_task_gate


def test_browser_rejects_foreign_company_filing_but_keeps_declared_peer():
    records = [
        {
            "evidence_id": "foreign_filing",
            "symbol": "MSFT",
            "title": "NVDA FY2024 Form 10-K annual report",
            "source_url": "https://www.sec.gov/Archives/nvda-2024-10k",
            "content": "NVIDIA fiscal 2024 filing.",
            "metadata": {},
        },
        {
            "evidence_id": "peer_snapshot",
            "symbol": "NVDA",
            "title": "NVDA current market snapshot",
            "source_url": "https://finance.yahoo.com/quote/NVDA",
            "content": "Peer comparison snapshot.",
            "metadata": {"evidence_role": "peer"},
        },
    ]

    accepted, meta = filter_evidence_for_target(records, expected_symbol="MSFT")

    assert [row["evidence_id"] for row in accepted] == ["peer_snapshot"]
    assert meta["rejected_count"] == 1
    assert meta["rejected"][0]["resolved_symbol"] == "NVDA"


def test_browser_rejects_foreign_investor_relations_page_without_ticker_prefix():
    accepted, meta = filter_evidence_for_target(
        [
            {
                "evidence_id": "foreign_ir",
                "symbol": "MSFT",
                "title": "Financial Info - SEC Filings - NVIDIA Corporation",
                "source_url": "https://investor.nvidia.com/financial-info/sec-filings/default.aspx",
                "content": "NVIDIA filings.",
                "metadata": {},
            }
        ],
        expected_symbol="MSFT",
    )

    assert accepted == []
    assert meta["rejected"][0]["resolved_symbol"] == "NVDA"


def test_task_id_cannot_override_company_mismatch():
    msft = Company(id=15, name="Microsoft Corporation", symbol="MSFT", market="US")
    nvda = Company(id=17, name="NVIDIA Corporation", symbol="NVDA", market="US")
    task = ReportTask(
        task_id="task-msft",
        company_id=msft.id,
        company=msft,
        symbol="MSFT",
        period="FY2024",
        metadata_json={"company_name": "Microsoft Corporation", "symbol": "MSFT"},
    )
    evidence = EvidenceItem(
        evidence_id="nvda_filing",
        company_id=nvda.id,
        company=nvda,
        source_type="sec_10k_filing",
        trust_level="official",
        title="NVDA FY2024 Form 10-K",
        content="NVIDIA filing",
        metadata_json={"task_id": "task-msft", "period": "FY2024", "symbol": "NVDA"},
    )

    assert _evidence_matches_task_gate(evidence, task=task, metadata=task.metadata_json) is False


def test_artifact_conversion_preserves_source_company_symbol():
    msft = Company(id=15, name="Microsoft Corporation", symbol="MSFT", market="US")
    nvda = Company(id=17, name="NVIDIA Corporation", symbol="NVDA", market="US")
    task = ReportTask(
        task_id="task-msft",
        company_id=msft.id,
        company=msft,
        symbol="MSFT",
        period="FY2024",
        metadata_json={"company_name": "Microsoft Corporation", "symbol": "MSFT"},
    )
    evidence = EvidenceItem(
        evidence_id="nvda_filing",
        company_id=nvda.id,
        company=nvda,
        source_type="sec_10k_filing",
        trust_level="official",
        title="NVDA FY2024 Form 10-K",
        content="NVIDIA filing",
        metadata_json={"task_id": "origin-nvda", "period": "FY2024", "symbol": "NVDA"},
    )

    record = _artifact_record_from_evidence(evidence, task=task, metadata=task.metadata_json)

    assert record["symbol"] == "NVDA"
    assert record["company_identity"]["symbol"] == "NVDA"
    assert record["metadata"]["expected_symbol"] == "MSFT"
    assert record["metadata"]["origin_task_id"] == "origin-nvda"


def test_immutable_source_identity_overrides_legacy_wrong_company_binding():
    msft = Company(id=15, name="Microsoft Corporation", symbol="MSFT", market="US")
    task = ReportTask(
        task_id="task-msft",
        company_id=msft.id,
        company=msft,
        symbol="MSFT",
        period="FY2024",
        metadata_json={"company_name": "Microsoft Corporation", "symbol": "MSFT"},
    )
    legacy_polluted = EvidenceItem(
        evidence_id="legacy_nvda_filing",
        company_id=msft.id,
        company=msft,
        source_type="sec_10k_filing",
        trust_level="official",
        title="NVDA FY2024 Form 10-K annual report",
        source_url="https://www.sec.gov/Archives/edgar/data/1045810/nvda-20240128.htm",
        content="NVIDIA filing",
        metadata_json={"task_id": "task-msft", "period": "FY2024", "symbol": "MSFT"},
    )

    assert _evidence_matches_task_gate(legacy_polluted, task=task, metadata=task.metadata_json) is False
    record = _artifact_record_from_evidence(legacy_polluted, task=task, metadata=task.metadata_json)
    assert record["symbol"] == "NVDA"
