from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.db.models import EvidenceItem, ReportClaim, ReportTask
from src.services.report_task_service import ReportTaskService


def test_web_dashboard_payload_and_page_contract(temp_db_engine, tmp_path):
    service = ReportTaskService(
        engine=temp_db_engine,
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
    )
    with service.session() as session:
        session.add_all(
            [
                ReportTask(task_id="task-dashboard-web", symbol="NVDA", period="FY2024", status="completed"),
                EvidenceItem(evidence_id="ev_dashboard", content="Evidence", source_type="sec_edgar"),
                ReportClaim(task_id="task-dashboard-web", claim_text="Claim", verification_status="supported", review_status="pending"),
            ]
        )
        session.commit()
    app = create_fastapi_app(
        output_dir=str(tmp_path / "legacy_outputs"),
        report_dir=str(tmp_path / "legacy_reports"),
        memory_root=str(tmp_path / "legacy_memory"),
        report_task_service=service,
    )

    with TestClient(app) as client:
        page = client.get("/workbench")
        summary = client.get("/api/dashboard/summary")
        funnel = client.get("/api/dashboard/funnel")

    assert page.status_code == 200
    html = page.text
    assert "慧研投研工作台" in html
    assert "投研首页" in html
    assert "投研空间" in html
    assert "股票池管理" in html
    assert "创建投研空间" in html
    assert "添加股票池公司" in html
    assert "创建研报任务" in html
    assert "公司或股票代码" in html
    assert "查询期间" in html
    assert "报告类型" in html
    assert "运行方式" in html
    assert "任务操作" in html
    assert "研究问题" in html
    assert "数据源范围" in html
    assert "启动" in html
    assert "取消" in html
    assert "重试" in html
    assert "归档" in html
    assert "taskCompanyInput" in html
    assert "companyCandidates" in html
    assert "data-open-create-task" in html
    assert "最近任务" in html
    assert "数据源健康" in html
    assert "复核异常" in html
    assert "最近研报任务" in html
    assert "数据源分布" in html
    assert "主张状态分布" in html
    assert "处理链路" in html
    assert "当前暂无真实处理数据" in html
    assert "当前真实统计尚未形成完整累计漏斗" in html
    assert "请切换到“处理链路”查看真实阶段计数" in html
    assert "isValidFunnelSeries" in html
    assert "最大流失步骤" in html
    assert "funnel-layer" in html
    assert "funnelVisual" in html
    assert "funnelLoss" in html
    assert "dataSourceHealth" in html
    assert "dataSourceChart" in html
    assert "claimStatusChart" in html
    assert "reviewExceptions" in html
    assert "recentTaskRows" in html
    assert 'getJson("/api/dashboard/summary")' in html
    assert 'getJson("/api/dashboard/funnel")' in html
    assert 'getJson("/api/report-tasks?limit=6")' in html
    assert 'getJson("/api/workspaces")' in html
    assert "/api/workspaces/${encodeURIComponent(workspaceId)}/companies" in html
    assert "resolveCompanyForTask" in html
    assert 'start: "start"' in html
    assert 'cancel: "cancel"' in html
    assert 'archive: "archive"' in html
    assert "scheduleTaskRefresh" in html
    assert 'terminalTaskStatuses' in html
    assert "shortTaskId" in html
    assert "确认${labels[action]}该研报任务" in html
    assert "/api/report-tasks" in html
    assert "/api/latest" not in html

    assert summary.status_code == 200
    assert summary.json()["evidence_count"] == 1
    assert summary.json()["review_pending_claim_count"] == 1
    assert funnel.status_code == 200
    assert any(step["key"] == "report_claim_generated" for step in funnel.json()["steps"])
