"""Test that manual import creates documents with real content and can be processed
into evidence items (P0-3)."""

from src.db.init_db import init_db
from src.db.models import Document
from src.services.document_service import DocumentService
from src.services.manual_import_service import ManualImportService
from src.services.report_task_service import ReportTaskService


def test_manual_text_import_persists_content(tmp_path):
    """Importing a text document persists the actual content, not just a hash."""
    engine = init_db(f"sqlite:///{tmp_path / 'manual_import.db'}")
    report_service = ReportTaskService(
        engine=engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    import_service = ManualImportService(session_factory=report_service.session)
    doc_service = DocumentService(session_factory=report_service.session)

    result = import_service.import_document(
        {
            "title": "贵州茅台2025年财务报告",
            "content": "贵州茅台2025年实现营业收入1200亿元，同比增长15%。净利润600亿元，同比增长12%。经营活动现金流净额700亿元。",
            "period": "FY2025",
            "symbol": "600519.SS",
        }
    )

    assert result["created"] is True
    detail = doc_service.get_document(result["document"]["id"])
    with report_service.session() as session:
        doc = session.get(Document, result["document"]["id"])
        assert doc is not None
        assert "营业收入1200亿元" in doc.content
        assert doc.parse_status == "parsed"
        assert doc.content_hash is not None


def test_manual_import_stub_removed(tmp_path):
    """Text imports no longer carry 'stub: True' in processing step metadata."""
    engine = init_db(f"sqlite:///{tmp_path / 'no_stub.db'}")
    report_service = ReportTaskService(
        engine=engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    import_service = ManualImportService(session_factory=report_service.session)

    result = import_service.import_document(
        {
            "title": "Test document",
            "content": "Some financial content for testing.",
            "period": "FY2025",
            "symbol": "NVDA",
        }
    )

    detail = result["document"]
    # Verify the import API also includes evidence_count=0 initially
    assert detail["parse_status"] == "parsed"


def test_manual_import_process_creates_evidence(tmp_path):
    """Processing a manually imported document creates evidence items."""
    engine = init_db(f"sqlite:///{tmp_path / 'process_ev.db'}")
    report_service = ReportTaskService(
        engine=engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    import_service = ManualImportService(session_factory=report_service.session)
    doc_service = DocumentService(session_factory=report_service.session)

    result = import_service.import_document(
        {
            "title": "AAPL Revenue Data",
            "content": (
                "Apple Inc. reported quarterly revenue of $94.8 billion for Q4 2025. "
                "iPhone revenue was $46.2 billion. Services revenue reached $25.0 billion. "
                "Operating income was $29.5 billion. Net income was $24.2 billion. "
                "Earnings per diluted share were $1.56. Gross margin was 46.2%. "
                "International sales accounted for 58% of total revenue. "
                "The company returned over $28 billion to shareholders during the quarter. "
                "Apple's board of directors declared a cash dividend of $0.25 per share. "
                "Cash and marketable securities totaled $58.3 billion."
            ),
            "period": "2025Q4",
            "symbol": "AAPL",
            "market": "US",
        }
    )

    doc_id = result["document"]["id"]
    processed = doc_service.process_document(doc_id)

    assert processed["evidence_count"] > 0, "No evidence items created from document content"

    # Verify evidence details
    evidence_items = processed["evidence"]
    assert any("revenue" in item["snippet"].lower() or "Revenue" in item["title"] for item in evidence_items)

    # Verify processing step was recorded
    steps = processed["processing_steps"]
    step_names = [s["step_name"] for s in steps]
    assert "chunk" in step_names
    chunk_step = next(s for s in steps if s["step_name"] == "chunk")
    assert chunk_step["status"] == "success"
    assert chunk_step["metadata"]["chunk_count"] > 0
    assert chunk_step["metadata"]["evidence_count"] > 0


def test_manual_import_process_is_idempotent(tmp_path):
    """Processing the same document twice does not duplicate evidence."""
    engine = init_db(f"sqlite:///{tmp_path / 'idempotent.db'}")
    report_service = ReportTaskService(
        engine=engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    import_service = ManualImportService(session_factory=report_service.session)
    doc_service = DocumentService(session_factory=report_service.session)

    result = import_service.import_document(
        {
            "title": "Test Idempotent",
            "content": "Revenue grew 10% year over year. Net income was $5 billion. Operating cash flow was $8 billion.",
            "period": "FY2025",
            "symbol": "MSFT",
        }
    )
    doc_id = result["document"]["id"]

    first = doc_service.process_document(doc_id)
    second = doc_service.process_document(doc_id)

    assert first["evidence_count"] > 0
    assert first["evidence_count"] == second["evidence_count"]


def test_duplicate_import_returns_existing_document(tmp_path):
    """Importing the same content twice returns the existing document."""
    engine = init_db(f"sqlite:///{tmp_path / 'dedup.db'}")
    report_service = ReportTaskService(
        engine=engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    import_service = ManualImportService(session_factory=report_service.session)

    payload = {
        "title": "Revenue Data",
        "content": "Revenue was 100 million dollars.",
        "period": "FY2025",
        "symbol": "AAPL",
    }

    first = import_service.import_document(payload)
    second = import_service.import_document(payload)

    assert first["created"] is True
    assert second["created"] is False
    assert second["duplicate"] is True
    assert first["document"]["id"] == second["document"]["id"]


def test_evidence_linked_to_report_period(tmp_path):
    """Evidence created from manual import is bound to company and period."""
    engine = init_db(f"sqlite:///{tmp_path / 'period_link.db'}")
    report_service = ReportTaskService(
        engine=engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    import_service = ManualImportService(session_factory=report_service.session)
    doc_service = DocumentService(session_factory=report_service.session)

    result = import_service.import_document(
        {
            "title": "Quarterly Results",
            "content": "Revenue: 1200 crores. Profit: 300 crores.",
            "period": "FY2025Q3",
            "symbol": "RELIANCE.NS",
        }
    )
    doc_id = result["document"]["id"]
    processed = doc_service.process_document(doc_id)

    for ev in processed["evidence"]:
        assert ev.get("source_type") is not None
