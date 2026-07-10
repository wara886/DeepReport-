from fastapi.testclient import TestClient

from src.app.api_fastapi import create_fastapi_app
from src.db.models import ClaimEvidence, DataSource, EvidenceItem, IngestionBatch, LLMRun, ReportClaim, ReportTask
from src.services.evaluation_service import EvaluationService
from src.services.report_task_service import ReportTaskService


def build_client(tmp_path):
    service = ReportTaskService(
        database_url=f"sqlite:///{tmp_path / 'evaluation.db'}",
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
    return TestClient(app), service


def write_sample_benchmark_suite(root):
    suite_dir = root / "quick9-fixed"
    suite_dir.mkdir(parents=True)
    (suite_dir / "benchmark_summary.csv").write_text(
        "metric,overall,US,HK,CN-A\n"
        "Delivery Pass Rate,0.667,1.0,0.0,1.0\n"
        "Objective Quality Score,88.5,92.0,80.0,93.5\n"
        "Traceable Claim Rate (Artifact-Derived),0.778,1.0,0.5,0.833\n",
        encoding="utf-8",
    )
    (suite_dir / "market_breakdown.csv").write_text(
        "market,case_count,quality_evaluable_count,delivery_pass_rate,objective_quality_score,traceable_claim_rate_artifact_derived\n"
        "Overall,9,8,0.667,88.5,0.778\n"
        "US,3,3,1.0,92.0,1.0\n"
        "HK,3,2,0.0,80.0,0.5\n"
        "CN-A,3,3,1.0,93.5,0.833\n",
        encoding="utf-8",
    )
    (suite_dir / "benchmark_failures.csv").write_text("case_id,market,status,category\nhk-1,HK,failed,runtime_or_model_failure\n", encoding="utf-8")
    (suite_dir / "benchmark_runs.jsonl").write_text('{"case_id":"us-1"}\n{"case_id":"hk-1"}\n', encoding="utf-8")
    return suite_dir


def seed_evaluation_state(service):
    with service.session() as session:
        task_ok = ReportTask(
            task_id="task-eval-ok",
            symbol="NVDA",
            period="FY2024",
            status="completed",
            quality_score=0.92,
            metadata_json={
                "company_name": "NVIDIA",
                "quality_result": {
                    "delivery_gate": {"delivery_pass": True},
                    "top_quality_issues": [],
                },
            },
        )
        task_bad = ReportTask(
            task_id="task-eval-bad",
            symbol="TSLA",
            period="FY2024",
            status="quality_failed",
            quality_score=0.62,
            metadata_json={
                "company_name": "Tesla",
                "quality_result": {
                    "delivery_gate": {"delivery_pass": False},
                    "top_quality_issues": [
                        {"category": "citation_missing", "severity": "blocker", "message": "风险段落缺少引用。"}
                    ],
                },
            },
        )
        task_source_gap = ReportTask(
            task_id="task-eval-source-gap",
            symbol="NVDA",
            period="FY2024",
            status="quality_failed",
            quality_score=0.58,
            metadata_json={
                "company_name": "NVIDIA",
                "market": "US",
                "quality_result": {
                    "delivery_gate": {"delivery_pass": False},
                    "top_quality_issues": [
                        {"category": "citation_missing", "severity": "blocker", "message": "缺少官方年报证据。"}
                    ],
                },
            },
        )
        task_archived = ReportTask(
            task_id="task-eval-archived",
            symbol="AAPL",
            period="FY2024",
            status="archived",
            quality_score=0.1,
        )
        task_cancelled = ReportTask(
            task_id="task-eval-cancelled",
            symbol="MSFT",
            period="FY2024",
            status="cancelled",
            quality_score=0.05,
        )
        task_queued = ReportTask(
            task_id="task-eval-queued",
            symbol="AAPL",
            period="FY2024",
            status="queued",
            quality_score=0.02,
        )
        session.add_all([task_ok, task_bad, task_source_gap, task_archived, task_cancelled, task_queued])
        session.flush()
        evidence = EvidenceItem(
            evidence_id="ev-eval-1",
            content="Gross margin and revenue evidence.",
            source_type="sec_edgar",
            trust_level="official",
        )
        session.add(evidence)
        session.flush()
        supported_claim = ReportClaim(
            task_id="task-eval-ok",
            claim_text="NVIDIA revenue increased.",
            verification_status="supported",
            numeric_check_status="passed",
            citation_check_status="passed",
            review_status="approved",
        )
        weak_claim = ReportClaim(
            task_id="task-eval-bad",
            claim_text="Tesla margin pressure will continue.",
            verification_status="failed",
            numeric_check_status="failed",
            citation_check_status="failed",
            review_status="pending",
        )
        source_gap_claim = ReportClaim(
            task_id="task-eval-source-gap",
            claim_text="NVIDIA data center demand accelerated materially.",
            verification_status="failed",
            numeric_check_status="passed",
            citation_check_status="failed",
            review_status="pending",
        )
        archived_claim = ReportClaim(
            task_id="task-eval-archived",
            claim_text="Archived claim should not affect metrics.",
            verification_status="supported",
            review_status="approved",
        )
        session.add_all([supported_claim, weak_claim, source_gap_claim, archived_claim])
        session.flush()
        session.add(ClaimEvidence(claim_id=supported_claim.id, evidence_item_id=evidence.id, support_type="supporting"))
        session.add_all(
            [
                DataSource(
                    name="美国证监会年报",
                    source_key="sec_edgar",
                    source_type="official_filing",
                    market_scope=["US"],
                    trust_level="official",
                    enabled=True,
                    credential_status="not_required",
                    last_status="failed",
                    last_error="SEC timeout",
                ),
                DataSource(
                    name="雅虎财经",
                    source_key="yahoo_finance",
                    source_type="market_data",
                    market_scope=["US", "HK"],
                    trust_level="secondary",
                    enabled=True,
                    credential_status="not_required",
                    last_status="success",
                ),
                DataSource(
                    name="Serper 搜索",
                    source_key="serper",
                    source_type="web_search",
                    market_scope=["US", "CN", "HK"],
                    trust_level="secondary",
                    enabled=True,
                    credential_status="required",
                    last_status="not_run",
                ),
                IngestionBatch(
                    batch_id="ing-sec-failed",
                    source_key="sec_edgar",
                    name="NVDA FY2024 SEC 采集",
                    target_type="filings",
                    symbol="NVDA",
                    period="FY2024",
                    status="failed",
                    item_count=1,
                    failed_count=1,
                    error_message="SEC timeout",
                ),
            ]
        )
        session.add_all(
            [
                LLMRun(
                    run_id="run-eval-ok",
                    task_id="task-eval-ok",
                    prompt_key="report_quality_gate",
                    model_role="quality_gate",
                    status="success",
                    schema_valid=True,
                    latency_ms=100,
                    cost_usd=0.002,
                ),
                LLMRun(
                    run_id="run-eval-failed",
                    task_id="task-eval-bad",
                    prompt_key="claim_verifier",
                    model_role="verifier",
                    status="failed",
                    schema_valid=False,
                    fallback_used=True,
                    latency_ms=300,
                    cost_usd=0.004,
                ),
            ]
        )
        session.commit()


def test_evaluation_summary_aggregates_quality_and_harness_metrics(tmp_path):
    client, service = build_client(tmp_path)
    seed_evaluation_state(service)

    with client:
        response = client.get("/api/evaluation/summary")

    assert response.status_code == 200
    body = response.json()
    metrics = body["metrics"]
    assert metrics["active_task_count"] == 5
    assert metrics["completed_task_count"] == 1
    assert metrics["quality_evaluated_task_count"] == 3
    assert metrics["delivery_pass_count"] == 1
    assert metrics["delivery_pass_rate"] == 0.3333
    assert metrics["evidence_ready_task_count"] == 1
    assert metrics["evidence_ready_task_rate"] == 0.3333
    assert metrics["source_quality_ready_task_count"] == 1
    assert metrics["source_quality_ready_task_rate"] == 0.3333
    assert metrics["retrieval_gap_task_count"] == 2
    assert metrics["source_gap_task_count"] == 2
    assert metrics["average_quality_score"] == 0.7067
    assert metrics["claim_count"] == 3
    assert metrics["traceable_claim_count"] == 1
    assert metrics["traceable_claim_rate"] == 0.3333
    assert metrics["verified_claim_count"] == 1
    assert metrics["numeric_failed_count"] == 1
    assert metrics["numeric_consistency_rate"] == 0.6667
    assert metrics["citation_failed_count"] == 2
    assert metrics["citation_support_rate"] == 0.3333
    assert metrics["schema_valid_rate"] == 0.5
    assert metrics["llm_success_rate"] == 0.5
    assert metrics["average_llm_latency_ms"] == 200
    assert metrics["llm_cost_usd"] == 0.006
    failure_labels = {item["label"] for item in body["failure_categories"]}
    assert "质量门禁阻塞" in failure_labels
    assert "引用缺失或不支持" in failure_labels
    assert "模型运行失败" in failure_labels
    assert len(body["quality_gates"]) >= 7
    assert body["recent_tasks"][0]["task_id"] in {"task-eval-ok", "task-eval-bad", "task-eval-source-gap"}
    assert body["model_health"]["fallback_count"] == 1
    assert body["retrieval_quality"]["evidence_ready_task_count"] == 1
    assert body["retrieval_quality"]["source_gap_task_count"] == 2
    assert body["retrieval_quality"]["returned_sources"][0]["label"] == "美国证监会披露"
    assert any(item["label"] == "证据召回可用率" for item in body["quality_gates"])
    assert any(item["label"] == "关键来源覆盖率" for item in body["quality_gates"])
    matrix = body["regression_matrix"]
    assert matrix["title"] == "研报质量回归矩阵"
    assert matrix["evaluated_count"] == 3
    assert matrix["passed_count"] == 1
    assert matrix["blocked_count"] == 2
    assert matrix["pass_rate"] == 0.3333
    rows = {row["task_id"]: row for row in matrix["rows"]}
    assert rows["task-eval-ok"]["status"] == "passed"
    assert rows["task-eval-ok"]["recommended_action"] == "可作为当前回归基线。"
    assert rows["task-eval-bad"]["status"] == "blocked"
    assert "交付门禁" in rows["task-eval-bad"]["failed_gate_labels"]
    assert "引用支持" in rows["task-eval-bad"]["failed_gate_labels"]
    assert rows["task-eval-bad"]["recommended_action"] == "先查看质量门禁失败原因，再补证据或修正文稿。"
    assert {gate["label"] for gate in rows["task-eval-source-gap"]["gates"]} >= {"证据覆盖", "关键来源", "可追溯主张"}


def test_evaluation_summary_imports_benchmark_suite_outputs(tmp_path):
    benchmark_root = tmp_path / "benchmarks"
    suite_dir = write_sample_benchmark_suite(benchmark_root)
    client, service = build_client(tmp_path)
    client.app.state.evaluation_service = EvaluationService(
        session_factory=service.session,
        benchmark_roots=[benchmark_root],
    )

    with client:
        response = client.get("/api/evaluation/summary")

    assert response.status_code == 200
    suites = response.json()["benchmark_suites"]
    assert len(suites) == 1
    suite = suites[0]
    assert suite["suite_name"] == "Quick-9 多市场跑批"
    assert suite["suite_type"] == "quick9"
    assert suite["artifact_dir"] == str(suite_dir)
    assert suite["metrics"]["delivery_pass_rate"] == 0.667
    assert suite["metrics"]["objective_quality_score"] == 88.5
    assert suite["metrics"]["traceable_claim_rate"] == 0.778
    assert suite["case_count"] == 9
    assert suite["evaluated_count"] == 8
    assert suite["failure_count"] == 1
    markets = {row["market"]: row for row in suite["market_breakdown"]}
    assert markets["HK"]["evaluated_count"] == 2
    assert markets["CN-A"]["traceable_claim_rate"] == 0.833
    assert set(suite["artifacts"]) >= {"summary_csv", "runs_jsonl", "failures_csv", "market_csv"}


def test_evaluation_summary_handles_empty_state(tmp_path):
    client, _service = build_client(tmp_path)

    with client:
        response = client.get("/api/evaluation/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["metrics"]["active_task_count"] == 0
    assert body["metrics"]["delivery_pass_rate"] == 0.0
    assert body["failure_categories"] == []
    assert body["regression_matrix"]["rows"] == []
    assert body["regression_matrix"]["pass_rate"] == 0.0
    assert "暂无研报任务" in body["notes"][0]


def test_evaluation_task_diagnostics_explains_local_quality_blockers(tmp_path):
    client, service = build_client(tmp_path)
    seed_evaluation_state(service)

    with client:
        response = client.get("/api/evaluation/report-tasks/task-eval-bad/diagnostics")

    assert response.status_code == 200
    body = response.json()
    assert body["task"]["task_id"] == "task-eval-bad"
    assert body["summary"]["delivery_pass"] is False
    assert body["summary"]["missing_evidence_count"] == 1
    assert body["summary"]["unsupported_claim_count"] == 1
    assert body["summary"]["numeric_conflict_count"] == 1
    assert body["summary"]["citation_gap_count"] == 1
    assert body["summary"]["pending_review_count"] == 1
    blocker_labels = {item["label"] for item in body["blockers"]}
    assert "质量门禁未通过" in blocker_labels
    assert "主张未获支持" in blocker_labels
    assert "数字不一致" in blocker_labels
    assert "引用缺失" in blocker_labels
    assert body["claim_issues"]["numeric_conflicts"][0]["claim_text"] == "Tesla margin pressure will continue."
    assert body["model_issues"][0]["reason"] == "模型运行失败"
    action_views = {item["view"] for item in body["recommended_actions"]}
    assert {"claims", "facts", "evidence", "promptops"}.issubset(action_views)


def test_evaluation_task_diagnostics_links_source_gaps_to_ingestion_and_datasources(tmp_path):
    client, service = build_client(tmp_path)
    seed_evaluation_state(service)

    with client:
        response = client.get("/api/evaluation/report-tasks/task-eval-source-gap/diagnostics")

    assert response.status_code == 200
    body = response.json()
    health = body["data_source_health"]
    assert health["market"] == "US"
    assert health["required_sources"] == ["sec_edgar", "yahoo_finance", "serper", "local_evidence"]
    rows = {item["source_key"]: item for item in health["source_rows"]}
    assert rows["sec_edgar"]["health_status"] == "failed"
    assert rows["sec_edgar"]["latest_batch"]["batch_id"] == "ing-sec-failed"
    assert rows["sec_edgar"]["latest_batch"]["error_message"] == "SEC timeout"
    remediation = rows["sec_edgar"]["remediation_batch"]
    assert remediation["source_key"] == "sec_edgar"
    assert remediation["target_type"] == "filings"
    assert remediation["symbol"] == "NVDA"
    assert remediation["period"] == "FY2024"
    assert remediation["metadata"]["task_id"] == "task-eval-source-gap"
    assert remediation["metadata"]["source"] == "evaluation_diagnostic_remediation"
    assert rows["serper"]["health_status"] == "credential_required"
    assert rows["local_evidence"]["health_status"] == "not_configured"
    assert any(item["next_view"] == "ingestion" and item["source_key"] == "sec_edgar" for item in health["gaps"])
    assert any(item["next_view"] == "datasources" and item["source_key"] == "serper" for item in health["gaps"])
    action_by_view = {item["view"]: item for item in body["recommended_actions"]}
    assert action_by_view["ingestion"]["ingestion_source"] == "sec_edgar"
    assert action_by_view["datasources"]["datasource_query"] in {"serper", "local_evidence"}


def test_evaluation_remediation_batch_payload_creates_traceable_unique_batch(tmp_path):
    client, service = build_client(tmp_path)
    seed_evaluation_state(service)

    with client:
        diagnostic = client.get("/api/evaluation/report-tasks/task-eval-source-gap/diagnostics")
        payload = {
            item["source_key"]: item["remediation_batch"]
            for item in diagnostic.json()["data_source_health"]["source_rows"]
        }["sec_edgar"]
        first = client.post("/api/ingestion-batches", json=payload)
        second = client.post("/api/ingestion-batches", json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["batch_id"] != second.json()["batch_id"]
    assert first.json()["batch_id"].startswith("rem-sec-edgar-nvda-fy2024-")
    assert first.json()["source_key"] == "sec_edgar"
    assert first.json()["metadata"]["task_id"] == "task-eval-source-gap"
    assert first.json()["metadata"]["source"] == "evaluation_diagnostic_remediation"


def test_evaluation_task_diagnostics_returns_404_for_missing_task(tmp_path):
    client, _service = build_client(tmp_path)

    with client:
        response = client.get("/api/evaluation/report-tasks/not-found/diagnostics")

    assert response.status_code == 404
