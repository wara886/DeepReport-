from test_task_analysis_api import _attach_citation_artifacts, build_client, seed_analysis_package


def test_report_task_analysis_returns_productized_argument_chain(tmp_path):
    client, service = build_client(tmp_path)
    seed_analysis_package(service)
    _attach_citation_artifacts(service, tmp_path, used=True)

    with client:
        response = client.get("/api/report-tasks/task-analysis/analysis")

    assert response.status_code == 200
    chain = response.json()["argument_chain"]
    assert chain["title"] == "NVIDIA FY2024 投资逻辑链"
    assert chain["readiness"]["total_stage_count"] == 6
    assert chain["readiness"]["completed_stage_count"] == 6
    assert chain["readiness"]["ready"] is True
    assert [stage["label"] for stage in chain["flow"]] == ["实体", "事件", "财务事实", "投资线索", "Claim", "报告章节"]
    assert {stage["key"]: stage["status"] for stage in chain["flow"]}["report_section"] == "done"
    assert any(node["stage_label"] == "报告章节" for node in chain["nodes"])
    assert any(node["stage"] == "investment_signal" and node["evidence_bound"] is True for node in chain["nodes"])
    assert any(edge["label"] == "写入报告章节" for edge in chain["edges"])
    assert chain["recommended_actions"][0]["label"] == "抽查论证链"


def test_report_task_analysis_argument_chain_exposes_actionable_gaps(tmp_path):
    client, service = build_client(tmp_path)
    with service.session() as session:
        from src.db.models import Company, ReportTask

        company = Company(name="Tesla Inc.", symbol="TSLA", market="US", industry="Automobiles")
        session.add(company)
        session.flush()
        session.add(
            ReportTask(
                task_id="task-chain-gap",
                company_id=company.id,
                symbol="TSLA",
                period="FY2025",
                report_type="annual_review",
                status="queued",
                current_stage="queued",
                metadata_json={"company_name": "Tesla", "research_topic": "分析 Tesla FY2025 风险"},
            )
        )
        session.commit()

    with client:
        response = client.get("/api/report-tasks/task-chain-gap/analysis")

    assert response.status_code == 200
    chain = response.json()["argument_chain"]
    assert chain["readiness"]["ready"] is False
    assert chain["readiness"]["completed_stage_count"] == 1
    assert {gap["key"] for gap in chain["gaps"]} == {"event", "financial_fact", "investment_signal", "claim", "report_section"}
    assert [action["view"] for action in chain["recommended_actions"]][:3] == ["evidence", "facts", "signals"]
