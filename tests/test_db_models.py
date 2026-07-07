from sqlalchemy import inspect, select

from src.db.models import (
    ClaimEvidence,
    Company,
    Document,
    DocumentProcessingStep,
    EvidenceItem,
    ReportArtifact,
    ReportClaim,
    ReportTask,
    ReportTaskEvent,
    ReviewRecord,
    Workspace,
    WorkspaceCompany,
)


def test_p0_models_expose_expected_columns(temp_db_engine):
    inspector = inspect(temp_db_engine)

    expected_columns = {
        "companies": {"id", "name", "symbol", "market", "industry", "aliases", "created_at"},
        "workspaces": {
            "id",
            "name",
            "slug",
            "market",
            "description",
            "keywords",
            "excluded_keywords",
            "focus_metrics",
            "risk_types",
            "evidence_threshold",
            "quality_gate_threshold",
            "default_data_sources",
            "report_template",
            "is_active",
            "metadata",
            "created_at",
        },
        "workspace_companies": {
            "id",
            "workspace_id",
            "company_id",
            "name",
            "symbol",
            "market",
            "industry",
            "aliases",
            "focus_metrics",
            "risk_types",
            "notes",
            "is_active",
            "metadata",
            "created_at",
        },
        "documents": {
            "id",
            "company_id",
            "datasource_id",
            "batch_id",
            "title",
            "doc_type",
            "report_period",
            "source_url",
            "file_path",
            "content_hash",
            "parse_status",
            "created_at",
        },
        "document_processing_steps": {
            "id",
            "document_id",
            "step_name",
            "status",
            "started_at",
            "finished_at",
            "error_message",
            "metadata",
        },
        "evidence_items": {
            "id",
            "evidence_id",
            "company_id",
            "document_id",
            "chunk_id",
            "source_type",
            "trust_level",
            "title",
            "content",
            "source_url",
            "page_no",
            "metadata",
            "created_at",
        },
        "report_tasks": {
            "id",
            "task_id",
            "workspace_id",
            "company_id",
            "symbol",
            "period",
            "report_type",
            "status",
            "current_stage",
            "quality_score",
            "created_at",
            "started_at",
            "finished_at",
            "error_message",
            "metadata",
        },
        "report_task_events": {"id", "task_id", "stage", "status", "message", "metadata", "created_at"},
        "report_artifacts": {"id", "task_id", "artifact_type", "path", "url", "created_at"},
        "report_claims": {
            "id",
            "task_id",
            "section_name",
            "claim_text",
            "claim_type",
            "is_critical",
            "critical_claim_type",
            "verification_status",
            "numeric_check_status",
            "citation_check_status",
            "confidence",
            "review_status",
            "metadata",
        },
        "claim_evidence": {"claim_id", "evidence_item_id", "support_type"},
        "review_records": {
            "id",
            "target_type",
            "target_id",
            "decision",
            "comment",
            "before_value",
            "after_value",
            "reviewer",
            "created_at",
        },
    }

    for table_name, column_names in expected_columns.items():
        actual = {column["name"] for column in inspector.get_columns(table_name)}
        assert column_names.issubset(actual)


def test_p0_model_relationship_round_trip(temp_db_session):
    company = Company(name="NVIDIA Corporation", symbol="NVDA", market="US", aliases=["NVIDIA", "NVDA"])
    workspace = Workspace(
        name="AI 投研空间",
        slug="ai-research",
        market="US",
        focus_metrics=["revenue", "gross_margin"],
        risk_types=["valuation", "supply_chain"],
        default_data_sources=["sec_edgar"],
    )
    workspace.companies.append(
        WorkspaceCompany(
            company=company,
            name="NVIDIA Corporation",
            symbol="NVDA",
            market="US",
            industry="Semiconductors",
            aliases=["英伟达", "NVIDIA", "NVDA"],
        )
    )
    document = Document(
        company=company,
        batch_id="batch-001",
        title="NVIDIA FY2024 Form 10-K",
        doc_type="10-K",
        report_period="FY2024",
        content_hash="hash-nvda-2024-10k",
        parse_status="parsed",
    )
    document.processing_steps.append(
        DocumentProcessingStep(step_name="chunk", status="success", metadata_json={"chunks": 12})
    )
    evidence = EvidenceItem(
        evidence_id="ev-001",
        company=company,
        document=document,
        chunk_id="chunk-1",
        source_type="filing",
        trust_level="official",
        title="Revenue disclosure",
        content="Revenue increased during fiscal 2024.",
        page_no=42,
        metadata_json={"section": "MD&A"},
    )
    task = ReportTask(
        task_id="task-001",
        company=company,
        symbol="NVDA",
        period="FY2024",
        status="running",
        current_stage="writer",
        metadata_json={"topic": "equity research"},
    )
    task.events.append(ReportTaskEvent(stage="planner", status="success", message="plan ready"))
    task.artifacts.append(ReportArtifact(artifact_type="html", path="reports/task-001/report.html"))
    claim = ReportClaim(
        task=task,
        section_name="Financials",
        claim_text="Revenue increased in fiscal 2024.",
        claim_type="financial",
        is_critical=True,
        verification_status="supported",
        review_status="pending",
        confidence=0.91,
    )
    claim.evidence_links.append(ClaimEvidence(evidence_item=evidence, support_type="supports"))
    review = ReviewRecord(
        target_type="claim",
        target_id="1",
        decision="approve",
        comment="Evidence supports the statement.",
        before_value={"review_status": "pending"},
        after_value={"review_status": "approved"},
        reviewer="analyst@example.com",
    )
    temp_db_session.add_all([workspace, review])
    temp_db_session.commit()

    task = temp_db_session.scalar(select(ReportTask).where(ReportTask.task_id == "task-001"))
    workspace = temp_db_session.scalar(select(Workspace).where(Workspace.slug == "ai-research"))

    assert task is not None
    assert task.company is not None
    assert task.company.symbol == "NVDA"
    assert task.events[0].stage == "planner"
    assert task.artifacts[0].artifact_type == "html"
    assert task.claims[0].evidence_links[0].evidence_item.evidence_id == "ev-001"
    assert task.claims[0].evidence_links[0].support_type == "supports"
    assert workspace is not None
    assert workspace.companies[0].symbol == "NVDA"
    assert workspace.companies[0].company is not None
    assert workspace.companies[0].company.symbol == "NVDA"

    step = temp_db_session.scalar(select(DocumentProcessingStep))
    assert step is not None
    assert step.metadata_json == {"chunks": 12}

    review = temp_db_session.scalar(select(ReviewRecord))
    assert review is not None
    assert review.after_value == {"review_status": "approved"}
