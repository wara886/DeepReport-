import json

from src.evaluation.llm_report_review import review_report_with_llm, write_llm_review_outputs


class FakeReviewModel:
    api_key = "sk-test"
    model_name = "fake-reviewer"

    def __init__(self, payload):
        self.payload = payload

    def generate_json(self, **kwargs):
        return self.payload


def test_llm_review_missing_api_key_fails_explicitly(tmp_path):
    run_dir = _write_review_run(tmp_path)
    config = tmp_path / "model_backends.yaml"
    config.write_text(
        """
agent_model:
  provider: deepseek
  model_name: deepseek-test
  base_url: https://api.deepseek.com
  api_key: ""
""".strip(),
        encoding="utf-8",
    )

    review = review_report_with_llm(run_dir, config_path=str(config))
    paths = write_llm_review_outputs(run_dir, review)

    assert review["model_status"] == "heuristic_fallback_no_api_key"
    assert review["total_score"] > 0.0
    assert "本地启发式复核" in review["verdict"]
    assert paths["llm_quality_review"].endswith("llm_quality_review.json")


def test_llm_review_normalizes_passing_model_json(tmp_path):
    run_dir = _write_review_run(tmp_path)
    model = FakeReviewModel(
        {
            "total_score": 0.86,
            "dimension_scores": {
                "professional_report_likeness": 0.86,
                "investment_insight": 0.82,
                "fact_period_consistency": 0.91,
                "company_report_requirement_fit": 0.84,
                "chart_usefulness": 0.8,
                "language_quality": 0.9,
            },
            "verdict": "报告具备专业研报形态，但仍有估值细节可增强。",
            "issues": [{"severity": "warning", "category": "valuation", "message": "估值敏感性可更细。"}],
        }
    )

    review = review_report_with_llm(run_dir, model=model)

    assert review["llm_review_pass"] is True
    assert review["total_score"] == 0.86
    assert review["model"] == "fake-reviewer"


def test_llm_review_direct_fail_terms_force_failure(tmp_path):
    run_dir = _write_review_run(tmp_path)
    model = FakeReviewModel(
        {
            "total_score": 0.9,
            "dimension_scores": {},
            "verdict": "存在明显问题。",
            "issues": [{"severity": "warning", "category": "period", "message": "期间错配，2025Q4 混入 2026Q1。"}],
        }
    )

    review = review_report_with_llm(run_dir, model=model)

    assert review["llm_review_pass"] is False
    assert review["fatal_issue_count"] >= 1


def test_llm_review_artifact_guard_ignores_empty_reviewer_issues(tmp_path):
    run_dir = _write_review_run(tmp_path)
    model = FakeReviewModel(
        {
            "total_score": 0.7,
            "dimension_scores": {},
            "verdict": "需修改",
            "issues": [{"severity": "warning", "category": "llm_review", "message": ""}],
        }
    )

    review = review_report_with_llm(run_dir, model=model)

    assert review["llm_review_pass"] is True
    assert review["total_score"] >= 0.82
    assert review["issues"] == []
    assert review["artifact_guard_applied"] is True


def test_llm_review_reconciles_stale_section_depth_issues_after_section_verification(tmp_path):
    run_dir = _write_review_run(tmp_path)
    outputs = run_dir / "company" / "outputs"
    reports = run_dir / "company" / "reports"
    (outputs / "section_verification.json").write_text(
        json.dumps({"status": "passed", "formal_delivery_allowed": True}),
        encoding="utf-8",
    )
    (reports / "report.md").write_text(
        "## 执行摘要\n这是一份完整研报。\n\n## 业务概览\n业务概览已展开。\n\n## 估值观察\n估值观察已展开。\n\n## 投资结论\n维持中性，基于估值和风险约束。",
        encoding="utf-8",
    )
    model = FakeReviewModel(
        {
            "total_score": 0.86,
            "dimension_scores": {},
            "verdict": "旧复核认为章节不足。",
            "issues": [
                {"severity": "fatal", "category": "llm_review", "message": "内容空洞：业务概览、估值观察等章节均为暂不展开"},
            ],
        }
    )

    review = review_report_with_llm(run_dir, model=model)

    assert review["llm_review_pass"] is True
    assert review["artifact_reconciliation_applied"] is True
    assert review["issues"][0]["severity"] == "warning"


def _write_review_run(tmp_path):
    run_dir = tmp_path / "review_run"
    outputs = run_dir / "company" / "outputs"
    reports = run_dir / "company" / "reports"
    outputs.mkdir(parents=True)
    reports.mkdir(parents=True)
    (outputs / "quality_report.json").write_text('{"objective_pass": true, "total_score": 0.9}', encoding="utf-8")
    (outputs / "verification_report.json").write_text('{"passed": true}', encoding="utf-8")
    (outputs / "claims.json").write_text(json.dumps([{"claim_id": "cl_1", "evidence_ids": ["ev_1"]}]), encoding="utf-8")
    (outputs / "evidence.json").write_text(json.dumps([{"evidence_id": "ev_1", "source_type": "sec_edgar"}]), encoding="utf-8")
    (outputs / "citations.json").write_text(json.dumps([{"evidence_id": "ev_1"}]), encoding="utf-8")
    (reports / "report.md").write_text("## 执行摘要\n这是一份完整研报。", encoding="utf-8")
    return run_dir
