from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.db.models import Company, Document, EvidenceItem, ReportTask
from src.services.report_task_service import ReportTaskService


def build_client(temp_db_engine, tmp_path):
    service = ReportTaskService(
        engine=temp_db_engine,
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
    return service, TestClient(app)


def seed_relation_evidence(service):
    with service.session() as session:
        company = Company(name="NVIDIA Corporation", symbol="NVDA", market="US", industry="Semiconductors")
        session.add(company)
        session.flush()
        document = Document(
            company_id=company.id,
            title="NVIDIA FY2024 Form 10-K",
            doc_type="10-K",
            report_period="FY2024",
            parse_status="parsed",
        )
        session.add(document)
        session.flush()
        session.add(
            EvidenceItem(
                evidence_id="ev_relation_api",
                company_id=company.id,
                document_id=document.id,
                source_type="sec_edgar",
                trust_level="official",
                title="Revenue and gross margin disclosure",
                content="NVIDIA revenue increased and gross margin expanded in FY2024.",
                metadata_json={"period": "FY2024"},
            )
        )
        session.commit()


def test_entity_and_relation_upsert_api_is_idempotent(temp_db_engine, tmp_path):
    service, client = build_client(temp_db_engine, tmp_path)
    seed_relation_evidence(service)

    company_payload = {
        "entity_type": "company",
        "canonical_name": "NVIDIA Corporation",
        "symbol": "NVDA",
        "market": "US",
        "source_evidence_id": "ev_relation_api",
    }
    metric_payload = {
        "entity_type": "metric",
        "canonical_name": "营业收入",
        "source_evidence_id": "ev_relation_api",
    }

    with client:
        first_company = client.post("/api/entities", json=company_payload)
        second_company = client.post("/api/entities", json=company_payload)
        metric = client.post("/api/entities", json=metric_payload)

    assert first_company.status_code == 201
    assert second_company.status_code == 201
    assert first_company.json()["id"] == second_company.json()["id"]
    assert metric.status_code == 201

    relation_payload = {
        "source_entity_id": first_company.json()["id"],
        "target_entity_id": metric.json()["id"],
        "relation_type": "HAS_METRIC",
        "source_evidence_id": "ev_relation_api",
        "confidence": 0.77,
    }
    with client:
        first_relation = client.post("/api/entity-relations", json=relation_payload)
        second_relation = client.post("/api/entity-relations", json=relation_payload)
        entities = client.get("/api/entities", params={"q": "NVIDIA"})
        relations = client.get("/api/entity-relations", params={"relation_type": "HAS_METRIC"})
        graph = client.get("/api/graph/summary")

    assert first_relation.status_code == 201
    assert second_relation.status_code == 201
    assert first_relation.json()["id"] == second_relation.json()["id"]
    assert first_relation.json()["source"]["canonical_name"] == "NVIDIA Corporation"
    assert first_relation.json()["target"]["canonical_name"] == "营业收入"
    assert entities.json()["total"] == 1
    assert relations.json()["total"] == 1
    assert graph.json()["node_count"] == 2
    assert graph.json()["edge_count"] == 1


def test_extract_entities_from_evidence_api_builds_graph(temp_db_engine, tmp_path):
    service, client = build_client(temp_db_engine, tmp_path)
    seed_relation_evidence(service)

    with client:
        extracted = client.post("/api/entities/extract-from-evidence", json={"evidence_id": "ev_relation_api"})
        graph = client.get("/api/graph/summary")

    assert extracted.status_code == 201
    assert extracted.json()["entity_count"] >= 4
    assert extracted.json()["relation_count"] >= 4
    assert graph.json()["node_count"] == extracted.json()["entity_count"]
    assert graph.json()["edge_count"] == extracted.json()["relation_count"]


def test_extract_entities_from_task_api_is_idempotent(temp_db_engine, tmp_path):
    service, client = build_client(temp_db_engine, tmp_path)
    with service.session() as session:
        company = Company(name="NVIDIA Corporation", symbol="NVDA", market="US", industry="Semiconductors")
        session.add(company)
        session.flush()
        task = ReportTask(
            task_id="task-entity-memory",
            company_id=company.id,
            symbol="NVDA",
            period="FY2024",
            report_type="annual_review",
            status="completed",
            current_stage="completed",
            metadata_json={"company_name": "NVIDIA"},
        )
        document = Document(
            company_id=company.id,
            batch_id="task-entity-memory",
            title="NVIDIA FY2024 Form 10-K",
            doc_type="10-K",
            report_period="FY2024",
            parse_status="parsed",
        )
        session.add_all([task, document])
        session.flush()
        session.add(
            EvidenceItem(
                evidence_id="ev_task_entity_memory",
                company_id=company.id,
                document_id=document.id,
                source_type="sec_edgar",
                trust_level="official",
                title="Revenue, gross margin, and supply chain risk disclosure",
                content="NVIDIA revenue increased, gross margin expanded, and supplier concentration created supply chain risk.",
                metadata_json={"period": "FY2024", "task_id": "task-entity-memory"},
            )
        )
        session.commit()

    with client:
        first = client.post("/api/entities/extract-from-task", json={"task_id": "task-entity-memory"})
        second = client.post("/api/entities/extract-from-task", json={"task_id": "task-entity-memory"})
        graph = client.get("/api/graph/summary")

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["task_id"] == "task-entity-memory"
    assert first.json()["evidence_count"] == 1
    assert first.json()["entity_count"] >= 5
    assert first.json()["relation_count"] >= 5
    assert second.json()["entity_count"] == first.json()["entity_count"]
    assert second.json()["relation_count"] == first.json()["relation_count"]
    assert graph.json()["node_count"] == first.json()["entity_count"]
    assert graph.json()["edge_count"] == first.json()["relation_count"]
