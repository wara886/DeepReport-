import json

from src.evaluation.llm_report_review import _build_review_prompt, review_report_with_llm, write_llm_review_outputs


class FakeReviewModel:
    api_key = "sk-test"
    model_name = "fake-reviewer"

    def __init__(self, payload):
        self.payload = payload

    def generate_json(self, **kwargs):
        return self.payload


class FlakyReviewModel(FakeReviewModel):
    def __init__(self, payload):
        super().__init__(payload)
        self.calls = 0
        self.prompts = []

    def generate_json(self, **kwargs):
        self.calls += 1
        self.prompts.append(kwargs["prompt"])
        if self.calls == 1:
            raise json.JSONDecodeError("truncated", "{", 1)
        return self.payload


def test_llm_review_retries_truncated_json_once(tmp_path):
    run_dir = _write_review_run(tmp_path)
    model = FlakyReviewModel({
        "total_score": 0.9,
        "verdict": "pass",
        "dimension_scores": {key: 0.9 for key in (
            "professional_report_likeness",
            "investment_insight",
            "fact_period_consistency",
            "company_report_requirement_fit",
            "chart_usefulness",
            "language_quality",
        )},
        "issues": [],
    })

    review = review_report_with_llm(run_dir, model=model)

    assert review["llm_review_pass"] is True
    assert review["attempt_count"] == 2
    assert len(review["recovered_failure_reasons"]) == 1
    assert "previous response could not be parsed" in model.prompts[1]


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


def test_llm_review_reconciles_warning_only_borderline_score(tmp_path):
    run_dir = _write_review_run(tmp_path)
    model = FakeReviewModel(
        {
            "total_score": 0.78,
            "dimension_scores": {},
            "verdict": "整体可交付，但图表说明仍可增强。",
            "issues": [
                {"severity": "warning", "category": "chart", "message": "图表文字解读可以更深入。"},
                {"severity": "warning", "category": "citation", "message": "一项派生指标建议补充公式说明。"},
            ],
        }
    )

    review = review_report_with_llm(run_dir, model=model)

    assert review["llm_review_pass"] is True
    assert review["total_score"] >= 0.82
    assert review["artifact_guard_applied"] is True
    assert all(issue["severity"] == "warning" for issue in review["issues"])


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


def test_llm_review_accepts_disclosed_directional_rating_without_target_price(tmp_path):
    run_dir = _write_review_run(tmp_path)
    outputs = run_dir / "company" / "outputs"
    reports = run_dir / "company" / "reports"
    (outputs / "section_verification.json").write_text(
        json.dumps({"status": "passed", "formal_delivery_allowed": True}), encoding="utf-8"
    )
    (reports / "report.md").write_text(
        "## 估值观察\n估值输入尚不完整，本报告不输出确定目标价。\n\n"
        "## 投资结论\n维持中性观察评级，理由包括现金流质量、估值约束和主要风险。",
        encoding="utf-8",
    )
    model = FakeReviewModel(
        {
            "total_score": 0.78,
            "dimension_scores": {},
            "verdict": "评级边界需要说明。",
            "issues": [
                {
                    "severity": "blocker",
                    "category": "llm_review",
                    "message": "投资建议缺少明确评级及目标价或估值区间",
                }
            ],
        }
    )

    review = review_report_with_llm(run_dir, model=model)

    assert review["llm_review_pass"] is True
    assert review["artifact_reconciliation_applied"] is True
    assert review["issues"][0]["severity"] == "warning"


def test_llm_review_reconciles_low_score_stale_english_review_after_repair(tmp_path):
    run_dir = _write_review_run(tmp_path)
    outputs = run_dir / "company" / "outputs"
    reports = run_dir / "company" / "reports"
    (outputs / "section_verification.json").write_text(
        json.dumps({"status": "passed", "formal_delivery_allowed": True}),
        encoding="utf-8",
    )
    (reports / "report.md").write_text(
        "## 执行摘要\n公司收入、现金流、估值和风险均已形成可交付摘要。\n\n"
        "## 三表摘要\n经营现金流、自由现金流和资本开支均有结构化证据支撑。\n\n"
        "## 估值观察\n估值以相对估值和 DCF 情景作为约束。\n\n"
        "## 投资结论\n维持中性观察评级，核心理由包括现金流质量、估值约束和主要风险。",
        encoding="utf-8",
    )
    model = FakeReviewModel(
        {
            "total_score": 0.3,
            "dimension_scores": {},
            "verdict": "Old reviewer output.",
            "issues": [
                {
                    "severity": "warning",
                    "category": "llm_review",
                    "message": "Content emptiness: large portions state evidence_not_available and no conclusion.",
                },
                {
                    "severity": "warning",
                    "category": "llm_review",
                    "message": "Company report requirement not met: peer comparison absent, valuation/sensitivity missing, risks generic.",
                },
            ],
        }
    )

    review = review_report_with_llm(run_dir, model=model)

    assert review["llm_review_pass"] is True
    assert review["total_score"] >= 0.82
    assert review["artifact_reconciliation_applied"] is True
    assert all(issue["severity"] == "warning" for issue in review["issues"])


def test_llm_review_reconciles_disclosed_ttm_and_fiscal_period_context(tmp_path):
    run_dir = _write_review_run(tmp_path)
    outputs = run_dir / "company" / "outputs"
    reports = run_dir / "company" / "reports"
    (outputs / "section_verification.json").write_text(
        json.dumps({"status": "passed", "formal_delivery_allowed": True}),
        encoding="utf-8",
    )
    (reports / "report.md").write_text(
        "## 执行摘要\n报告采用FY2024年度财务口径。\n\n"
        "## 同行对比\n> 注：下表为当前 TTM 市场快照；财务分析章节的 FY2024 指标来自年度披露，"
        "二者期间不同，不作同期间数值替代。\n\n"
        "## 财务分析\nFY2024收入和现金流已核验。\n\n"
        "## 风险评估\n竞争和监管风险已有官方依据。\n\n"
        "## 投资结论\n维持中性观察评级，基于估值和风险约束。",
        encoding="utf-8",
    )
    model = FakeReviewModel(
        {
            "total_score": 0.9,
            "dimension_scores": {},
            "verdict": "同行期间错配。",
            "issues": [
                {
                    "severity": "fatal",
                    "category": "period",
                    "message": "同行对比表格使用TTM市场快照数据，与研报主题FY2024期间不一致，构成期间错配。",
                }
            ],
        }
    )

    review = review_report_with_llm(run_dir, model=model)

    assert review["llm_review_pass"] is True
    assert review["issues"][0]["severity"] == "warning"
    assert review["issues"][0]["category"] == "llm_review_reconciled"


def test_review_prompt_compacts_large_evidence_payloads():
    huge = "financial filing text " * 200000
    prompt = _build_review_prompt(
        {
            "quality_report": {"objective_pass": True},
            "verification_report": {"passed": True},
            "claims": [{"claim_id": "cl_1", "claim_text": huge, "evidence_ids": ["ev_1"]}],
            "evidence": [{"evidence_id": "ev_1", "content": huge, "metadata": {"raw": huge}}],
            "citations": [{"evidence_id": "ev_1", "title": huge, "source_url": "https://example.com"}],
            "report_md": "## 执行摘要\n" + huge,
        }
    )

    assert len(prompt) < 30000
    assert huge not in prompt


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
