from fastapi.testclient import TestClient
import json

from src.app.api_fastapi import create_fastapi_app
from src.db.models import Company, Document, EvidenceItem
from src.services.report_task_service import ReportTaskService


class CountingOrchestrator:
    calls = 0

    def __init__(self, output_dir, report_dir, **kwargs):
        self.output_dir = output_dir
        self.report_dir = report_dir

    def run(self, **kwargs):
        type(self).calls += 1
        return {"verification_passed": True, "quality_score": 0.9}


class WeakArtifactOrchestrator:
    calls = 0

    def __init__(self, output_dir, report_dir, **kwargs):
        self.output_dir = output_dir
        self.report_dir = report_dir

    def run(self, **kwargs):
        type(self).calls += 1
        from pathlib import Path

        output_dir = Path(self.output_dir)
        report_dir = Path(self.report_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        report_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "evidence.json").write_text(
            json.dumps(
                [
                    {
                        "evidence_id": "ev_local_profile",
                        "source_type": "company_profile",
                        "trust_level": "medium",
                        "title": "Local company profile",
                        "content": "NVIDIA is a semiconductor company.",
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (output_dir / "claims.json").write_text(
            json.dumps(
                [
                    {
                        "claim_id": "cl_local_summary",
                        "section_name": "执行摘要",
                        "claim_text": "NVIDIA has an investable AI business profile.",
                        "evidence_ids": ["ev_local_profile"],
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (report_dir / "report.md").write_text(
            "# NVDA FY2024 公司研报\n\n"
            "## 执行摘要\n本节暂不展开详细分析（evidence_not_available）。\n\n"
            "## 风险评估\n待官方风险章节进一步校验。\n\n"
            "## 投资结论\n审慎观察。\n",
            encoding="utf-8",
        )
        (report_dir / "report.html").write_text("<html><body><h1>NVDA FY2024 公司研报</h1></body></html>", encoding="utf-8")
        return {"verification_passed": True, "quality_score": 0.5}


def passing_quality_runner(output_dir, report_dir, **kwargs):
    return {
        "quality_report": {"objective_pass": True, "total_score": 0.92},
        "llm_quality_review": {"llm_review_pass": True, "total_score": 0.9, "model_status": "test"},
        "delivery_gate": {"delivery_pass": True, "objective_pass": True, "llm_review_pass": True},
        "top_quality_issues": [],
    }


def build_client(tmp_path):
    CountingOrchestrator.calls = 0
    service = ReportTaskService(
        database_url=f"sqlite:///{tmp_path / 'tasks.db'}",
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
        orchestrator_factory=CountingOrchestrator,
        quality_runner=passing_quality_runner,
    )
    app = create_fastapi_app(
        output_dir=str(tmp_path / "legacy_outputs"),
        report_dir=str(tmp_path / "legacy_reports"),
        memory_root=str(tmp_path / "legacy_memory"),
        report_task_service=service,
    )
    return service, TestClient(app)


def build_client_with_orchestrator(tmp_path, orchestrator_factory):
    service = ReportTaskService(
        database_url=f"sqlite:///{tmp_path / 'tasks.db'}",
        output_root=tmp_path / "outputs",
        report_root=tmp_path / "reports",
        memory_root=tmp_path / "memory",
        orchestrator_factory=orchestrator_factory,
        quality_runner=passing_quality_runner,
    )
    app = create_fastapi_app(
        output_dir=str(tmp_path / "legacy_outputs"),
        report_dir=str(tmp_path / "legacy_reports"),
        memory_root=str(tmp_path / "legacy_memory"),
        report_task_service=service,
    )
    return service, TestClient(app)


def seed_official_evidence(service, *, task_id: str | None = None):
    seed_task_evidence(service, task_id=task_id, source_type="sec_edgar", trust_level="official")


def seed_task_evidence(
    service,
    *,
    task_id: str | None = None,
    source_type: str = "sec_edgar",
    trust_level: str = "official",
):
    with service.session() as session:
        company = Company(name="NVIDIA Corporation", symbol="NVDA", market="US")
        session.add(company)
        session.flush()
        document = Document(
            company_id=company.id,
            batch_id=task_id or "batch-nvda-fy2024",
            title="NVIDIA FY2024 Form 10-K",
            doc_type="10-K",
            report_period="FY2024",
            source_url="https://example.com/nvda-10k",
            parse_status="parsed",
        )
        session.add(document)
        session.flush()
        session.add(
            EvidenceItem(
                evidence_id=f"ev_gate_{source_type}_{task_id or 'source'}",
                company_id=company.id,
                document_id=document.id,
                source_type=source_type,
                trust_level=trust_level,
                title="FY2024 revenue evidence",
                content="NVIDIA revenue increased in fiscal 2024.",
                metadata_json={"period": "FY2024", "task_id": task_id} if task_id else {"period": "FY2024"},
            )
        )
        session.commit()


def seed_company_evidence(
    service,
    *,
    task_id: str,
    symbol: str,
    company_name: str,
    market: str,
    period: str,
    source_type: str,
    title: str,
    content: str,
):
    with service.session() as session:
        company = Company(name=company_name, symbol=symbol, market=market)
        session.add(company)
        session.flush()
        document = Document(
            company_id=company.id,
            batch_id=f"batch-{task_id}",
            title=title,
            doc_type="annual_report",
            report_period=period,
            source_url=f"https://example.com/{task_id}",
            parse_status="parsed",
        )
        session.add(document)
        session.flush()
        session.add(
            EvidenceItem(
                evidence_id=f"ev_{task_id}",
                company_id=company.id,
                document_id=document.id,
                source_type=source_type,
                trust_level="official",
                title=title,
                content=content,
                metadata_json={"period": period, "company_name": company_name, "symbol": symbol},
            )
        )
        session.commit()


def test_enforced_evidence_gate_blocks_generation_without_evidence(tmp_path):
    _, client = build_client(tmp_path)

    with client:
        response = client.post(
            "/api/report-tasks",
            json={
                "task_id": "task-gate-block",
                "symbol": "NVDA",
                "period": "FY2024",
                    "company_name": "NVIDIA",
                    "enforce_evidence_gate": True,
                    "run_immediately": True,
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "quality_failed"
    assert body["current_stage"] == "evidence_gate_failed"
    assert CountingOrchestrator.calls == 0
    gate = body["metadata"]["pre_generation_evidence_gate"]
    assert gate["blocked"] is True
    assert gate["draft_ready"] is False
    assert gate["delivery_ready"] is False
    assert gate["delivery_blocked_reasons"]
    assert gate["coverage"]["evidence_ready"] is False
    assert any(reason["type"] == "no_evidence" for reason in gate["blocking_reasons"])
    assert body["events"][-1]["stage"] == "evidence_gate"
    assert body["events"][-1]["status"] == "failed"


def test_enforced_evidence_gate_allows_generation_with_required_official_source(tmp_path):
    service, client = build_client(tmp_path)
    seed_official_evidence(service)

    with client:
        response = client.post(
            "/api/report-tasks",
            json={
                "task_id": "task-gate-pass",
                "symbol": "NVDA",
                "period": "FY2024",
                    "company_name": "NVIDIA",
                    "enforce_evidence_gate": True,
                    "run_immediately": True,
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "completed"
    assert CountingOrchestrator.calls == 1
    gate = body["metadata"]["pre_generation_evidence_gate"]
    assert gate["blocked"] is False
    assert gate["draft_ready"] is True
    assert gate["delivery_ready"] is True
    assert gate["delivery_blocked_reasons"] == []
    assert gate["status"] == "success"
    assert gate["coverage"]["quality_ready"] is True
    assert gate["coverage"]["returned_sources"] == ["sec_edgar"]
    curated_path = (
        tmp_path
        / "outputs"
        / "runs"
        / "task-gate-pass"
        / "outputs"
        / "retrieval_curated"
        / "task_evidence.jsonl"
    )
    curated_records = [json.loads(line) for line in curated_path.read_text(encoding="utf-8").splitlines() if line]
    assert [item["evidence_id"] for item in curated_records] == ["ev_gate_sec_edgar_source"]


def test_evidence_gate_excludes_wrong_period_financials_and_dedupes_snapshots(tmp_path):
    service, client = build_client(tmp_path)
    with service.session() as session:
        company = Company(name="Apple Inc.", symbol="AAPL", market="US")
        session.add(company)
        session.flush()
        document = Document(
            company_id=company.id,
            batch_id="batch-aapl-history",
            title="AAPL reusable evidence",
            doc_type="market_data",
            report_period="FY2024",
            source_url="https://finance.yahoo.com/quote/AAPL",
            parse_status="parsed",
        )
        session.add(document)
        session.flush()
        for suffix in ["old", "new"]:
            session.add(
                EvidenceItem(
                    evidence_id=f"aapl-snapshot-{suffix}",
                    company_id=company.id,
                    document_id=document.id,
                    source_type="market_api",
                    trust_level="medium",
                    title="AAPL Yahoo Finance market snapshot",
                    content="Current market price context.",
                    source_url="https://finance.yahoo.com/quote/AAPL",
                    metadata_json={"period": "FY2024", "context_type": "current_market_snapshot"},
                )
            )
        session.add(
            EvidenceItem(
                evidence_id="aapl-wrong-period-financials",
                company_id=company.id,
                document_id=document.id,
                source_type="market_api",
                trust_level="medium",
                title="AAPL Yahoo Finance financial data",
                content="Latest annual financials.",
                source_url="https://finance.yahoo.com/quote/AAPL/key-statistics",
                metadata_json={
                    "period": "FY2024",
                    "financials": {"income_history": [{"end_date": "2025-09-30", "Total Revenue": 1.0}]},
                },
            )
        )
        session.commit()

    with client:
        created = client.post(
            "/api/report-tasks",
            json={"task_id": "task-aapl-dedupe", "symbol": "AAPL", "period": "FY2024"},
        ).json()
        gate = service.run_evidence_gate(created["task_id"])

    assert gate["coverage"]["candidate_count"] == 1
    assert gate["coverage"]["returned_sources"] == ["market_api"]


def test_task_official_db_evidence_is_merged_into_report_artifacts_before_quality_gate(tmp_path):
    WeakArtifactOrchestrator.calls = 0
    service, client = build_client_with_orchestrator(tmp_path, WeakArtifactOrchestrator)
    seed_official_evidence(service)

    with client:
        response = client.post(
            "/api/report-tasks",
            json={
                "task_id": "task-official-artifact-merge",
                "symbol": "NVDA",
                "period": "FY2024",
                    "company_name": "NVIDIA",
                    "enforce_evidence_gate": True,
                    "run_immediately": True,
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "completed"
    assert WeakArtifactOrchestrator.calls == 1

    output_dir = tmp_path / "outputs" / "runs" / "task-official-artifact-merge" / "outputs"
    report_dir = tmp_path / "reports" / "runs" / "task-official-artifact-merge" / "reports"
    evidence = json.loads((output_dir / "evidence.json").read_text(encoding="utf-8"))
    claims = json.loads((output_dir / "claims.json").read_text(encoding="utf-8"))
    citations = json.loads((output_dir / "citations.json").read_text(encoding="utf-8"))
    report_md = (report_dir / "report.md").read_text(encoding="utf-8")
    report_html = (report_dir / "report.html").read_text(encoding="utf-8")

    official_id = "ev_gate_sec_edgar_source"
    assert any(item["evidence_id"] == official_id and item["source_authority"] == "official" for item in evidence)
    assert any(official_id in claim.get("evidence_ids", []) for claim in claims)
    assert any(item["evidence_id"] == official_id and item["used_in_report"] is True for item in citations)
    assert official_id in report_md
    assert "本节暂不展开详细分析" not in report_md
    assert "中性 / 审慎观察" in report_md
    assert "正式投资建议仍缺少完整预测模型" in report_md
    assert "参考来源" in report_html
    assert "FY2024 revenue evidence" in report_html


def test_task_report_patch_uses_market_meta_tags_and_avoids_truncated_english_sections(tmp_path):
    cases = [
        {
            "task_id": "task-us-meta-report",
            "symbol": "NVDA",
            "company_name": "NVIDIA",
            "market": "US",
            "period": "FY2024",
            "source_type": "sec_edgar",
            "title": "NVIDIA FY2024 Form 10-K",
            "content": "NVIDIA reported revenue growth, gross margin expansion, supply constraints, regulatory exposure, and intense competition in accelerated computing markets.",
            "required_source": "美国证监会披露",
        },
        {
            "task_id": "task-hk-meta-report",
            "symbol": "0700.HK",
            "company_name": "腾讯控股",
            "market": "HK",
            "period": "FY2024",
            "source_type": "hkex_announcement",
            "title": "腾讯控股 FY2024 港交所年报",
            "content": "Tencent annual report disclosed revenue, gross profit, operating cash flow, regulatory risk, gaming business, advertising demand, cloud services and shareholder return.",
            "required_source": "港交所披露",
        },
        {
            "task_id": "task-a-meta-report",
            "symbol": "600519.SS",
            "company_name": "贵州茅台",
            "market": "CN",
            "period": "FY2024",
            "source_type": "cninfo_announcement",
            "title": "贵州茅台 FY2024 巨潮资讯年报",
            "content": "Kweichow Moutai annual report disclosed revenue, net profit, cash flow, channel inventory, baijiu demand, regulatory policy and shareholder dividend plan.",
            "required_source": "巨潮资讯披露",
        },
    ]
    for case in cases:
        WeakArtifactOrchestrator.calls = 0
        service, client = build_client_with_orchestrator(tmp_path / case["task_id"], WeakArtifactOrchestrator)
        seed_company_evidence(
            service,
            task_id=case["task_id"],
            symbol=case["symbol"],
            company_name=case["company_name"],
            market=case["market"],
            period=case["period"],
            source_type=case["source_type"],
            title=case["title"],
            content=case["content"],
        )

        with client:
            response = client.post(
                "/api/report-tasks",
                json={
                    "task_id": case["task_id"],
                    "symbol": case["symbol"],
                    "period": case["period"],
                        "company_name": case["company_name"],
                        "enforce_evidence_gate": True,
                        "run_immediately": True,
                },
            )

        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "completed"
        report_dir = tmp_path / case["task_id"] / "reports" / "runs" / case["task_id"] / "reports"
        report_md = (report_dir / "report.md").read_text(encoding="utf-8")

        assert case["required_source"] in report_md
        assert "元标签" not in report_md
        assert "适合作为草稿" not in report_md
        assert "估值输入不足" not in report_md
        assert "收入表现" in report_md
        assert "风险披露" in report_md
        assert "本节暂不展开详细分析" not in report_md
        assert "evidence_not_available" not in report_md
        assert "..." not in report_md
        assert "reported revenue growth" not in report_md
        assert "annual report disclosed" not in report_md
        assert "Kweichow Moutai" not in report_md


def test_report_patch_preserves_substantive_writer_section_that_mentions_data_gap():
    from src.services.report_task_service import _patch_report_markdown_with_official_evidence

    writer_valuation = (
        "当前滚动市盈率约38.2倍，财务期间为FY2024，行情时点为当前日期。"
        "该倍数反映市场对服务收入、现金流和品牌壁垒的较高预期。"
        "若收入或利润率不及预期，估值倍数与盈利可能同步承压。"
        "完整目标价模型仍待补充长期增长率假设，但不影响当前倍数观察。"
    )
    markdown = f"# AAPL报告\n\n## 估值观察\n{writer_valuation}\n"

    updated = _patch_report_markdown_with_official_evidence(
        markdown,
        official_records=[
            {
                "evidence_id": "sec_aapl",
                "source_type": "sec_edgar",
                "source_authority": "official",
                "title": "AAPL Form 10-K",
                "content": "Revenue and risk disclosures.",
            }
        ],
        claims=[],
        metadata={"symbol": "AAPL", "company_name": "Apple Inc.", "period": "FY2024"},
    )

    assert writer_valuation in updated
    assert "估值口径：估值应区分" not in updated


def test_enforced_evidence_gate_blocks_delivery_when_official_source_is_missing(tmp_path):
    service, client = build_client(tmp_path)
    seed_task_evidence(service, source_type="local_evidence", trust_level="primary")

    with client:
        response = client.post(
            "/api/report-tasks",
            json={
                "task_id": "task-gate-official-gap",
                "symbol": "NVDA",
                "period": "FY2024",
                    "company_name": "NVIDIA",
                    "enforce_evidence_gate": True,
                    "run_immediately": True,
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "quality_failed"
    assert CountingOrchestrator.calls == 0
    gate = body["metadata"]["pre_generation_evidence_gate"]
    assert gate["blocked"] is True
    assert gate["draft_ready"] is False
    assert gate["delivery_ready"] is False
    assert gate["coverage"]["evidence_ready"] is True
    assert gate["coverage"]["quality_ready"] is False
    assert gate["coverage"]["returned_sources"] == ["local_evidence"]
    assert gate["coverage"]["missing_sources"] == ["sec_edgar"]
    assert any("美国证监会披露" in reason["description"] for reason in gate["delivery_blocked_reasons"])


def test_default_evidence_gate_records_warning_without_blocking_legacy_fast_task(tmp_path):
    _, client = build_client(tmp_path)

    with client:
        response = client.post(
            "/api/report-tasks",
                json={"task_id": "task-gate-warning", "symbol": "AAPL", "period": "FY2024", "run_immediately": True},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "completed"
    assert CountingOrchestrator.calls == 1
    gate = body["metadata"]["pre_generation_evidence_gate"]
    assert gate["status"] == "warning"
    assert gate["blocked"] is False
    assert gate["draft_ready"] is True
    assert gate["delivery_ready"] is False
    assert any(reason["type"] == "no_evidence" for reason in gate["delivery_blocked_reasons"])
    assert gate["coverage"]["evidence_ready"] is False
