from src.db.models import Company, Document, EvidenceItem
from src.services.entity_service import EntityService
from src.services.report_task_service import ReportTaskService


def build_entity_service(temp_db_engine, tmp_path):
    report_service = ReportTaskService(
        engine=temp_db_engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    return report_service, EntityService(session_factory=report_service.session)


def seed_entity_evidence(report_service):
    with report_service.session() as session:
        company = Company(name="NVIDIA Corporation", symbol="NVDA", market="US", industry="Semiconductors")
        session.add(company)
        session.flush()
        document = Document(
            company_id=company.id,
            batch_id="entity-batch",
            title="NVIDIA FY2024 Form 10-K",
            doc_type="10-K",
            report_period="FY2024",
            source_url="https://example.com/nvda-10k",
            parse_status="parsed",
        )
        session.add(document)
        session.flush()
        evidence = EvidenceItem(
            evidence_id="ev_entity_schema",
            company_id=company.id,
            document_id=document.id,
            source_type="sec_edgar",
            trust_level="official",
            title="Revenue, gross margin, and supply chain risk",
            content=(
                "Revenue increased in fiscal 2024, gross margin expanded, "
                "and supply chain risk remained a disclosure item."
            ),
            source_url="https://example.com/nvda-10k#page=42",
            metadata_json={"period": "FY2024"},
        )
        session.add(evidence)
        session.commit()


def test_extract_entities_from_evidence_uses_business_schema(temp_db_engine, tmp_path):
    report_service, entity_service = build_entity_service(temp_db_engine, tmp_path)
    seed_entity_evidence(report_service)

    payload = entity_service.extract_from_evidence("ev_entity_schema")

    entity_types = {item["entity_type"] for item in payload["entities"]}
    relation_types = {item["relation_type"] for item in payload["relations"]}
    metric_names = {item["canonical_name"] for item in payload["entities"] if item["entity_type"] == "metric"}

    assert {"company", "document", "metric", "risk_event"}.issubset(entity_types)
    assert {"营业收入", "毛利率"}.issubset(metric_names)
    assert {"PUBLISHED", "HAS_METRIC", "HAS_EVENT", "MENTIONED_IN"}.issubset(relation_types)
    assert payload["entity_count"] >= 5
    assert payload["relation_count"] >= 5
    assert all(item["source_evidence_id"] == "ev_entity_schema" for item in payload["relations"])

    graph = entity_service.graph_summary()
    assert graph["node_count"] == payload["entity_count"]
    assert graph["edge_count"] == payload["relation_count"]
