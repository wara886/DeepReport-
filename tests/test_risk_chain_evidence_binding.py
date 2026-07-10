from test_task_analysis_api import _attach_citation_artifacts, build_client, seed_analysis_package


def test_report_task_analysis_risk_chain_binds_evidence_fact_claim_and_section(tmp_path):
    client, service = build_client(tmp_path)
    seed_analysis_package(service)
    _attach_citation_artifacts(service, tmp_path, used=True)

    with client:
        response = client.get("/api/report-tasks/task-analysis/analysis")

    assert response.status_code == 200
    risk_chain = response.json()["risk_chain"]
    assert risk_chain["risk_count"] == 1
    assert risk_chain["readiness"]["evidence_bound_count"] == 1
    assert risk_chain["readiness"]["ready"] is True
    assert risk_chain["gaps"] == []
    path = risk_chain["exposure_paths"][0]
    assert path["title"] == "毛利率下滑"
    assert path["evidence_binding"]["ready"] is True
    assert path["evidence_binding"]["evidence_ids"] == ["ev-analysis-margin"]
    assert path["source_fact"]["title"] == "毛利率 53.0% FY2024"
    assert path["affected_claims"][0]["section_name"] == "盈利能力"
    assert path["affected_sections"] == ["盈利能力", "风险提示"]
    assert [item["stage"] for item in path["transmission"]] == ["证据", "财务事实", "投资线索", "Claim", "报告章节"]


def test_report_task_analysis_risk_chain_exposes_missing_claim_gap(tmp_path):
    client, service = build_client(tmp_path)
    seed_analysis_package(service)
    with service.session() as session:
        from src.db.models import ReportClaim

        session.query(ReportClaim).filter(ReportClaim.task_id == "task-analysis").delete()
        session.commit()

    with client:
        response = client.get("/api/report-tasks/task-analysis/analysis")

    assert response.status_code == 200
    risk_chain = response.json()["risk_chain"]
    assert risk_chain["readiness"]["ready"] is False
    assert {gap["key"] for gap in risk_chain["gaps"]} == {"risk_claim_gap"}
    assert risk_chain["recommended_actions"][0]["label"] == "补齐风险主张"
    assert risk_chain["exposure_paths"][0]["evidence_binding"]["ready"] is True
    assert risk_chain["exposure_paths"][0]["affected_claims"] == []
