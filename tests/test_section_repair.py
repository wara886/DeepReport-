import json

from src.evaluation.section_repair import repair_failed_sections_for_outputs
from src.evaluation.section_verification import write_section_verification


def test_section_repair_rewrites_failed_core_sections_and_rechecks(tmp_path):
    outputs = tmp_path / "outputs"
    reports = tmp_path / "reports"
    outputs.mkdir()
    reports.mkdir()
    markdown = """# 测试报告

## 执行摘要
短。

## 财务分析
本报告分别披露相对估值与

## 估值观察
估值分析待补。

## 风险评估
风险较多。

## 投资结论
观察。
"""
    (reports / "report.md").write_text(markdown, encoding="utf-8")
    (reports / "report.html").write_text("<html><body>old</body></html>", encoding="utf-8")
    (reports / "report.json").write_text(json.dumps({"title": "测试报告"}), encoding="utf-8")
    (outputs / "claims.json").write_text(
        json.dumps(
            [
                {
                    "section_name": "financial_analysis",
                    "claim_text": "收入增长与现金流质量需要一起观察，FY2024 revenue 为 100 亿元。[ev_fin]",
                    "evidence_ids": ["ev_fin"],
                },
                {
                    "section_name": "valuation",
                    "claim_text": "估值需要同时参考收入增速、毛利率和现金流质量。[ev_val]",
                    "evidence_ids": ["ev_val"],
                },
                {
                    "section_name": "risks",
                    "claim_text": "需求放缓和竞争加剧可能压缩利润率。[ev_risk]",
                    "evidence_ids": ["ev_risk"],
                },
                {
                    "section_name": "conclusion",
                    "claim_text": "基于估值约束和风险边界，维持审慎观察。[ev_conclusion]",
                    "evidence_ids": ["ev_conclusion"],
                },
            ]
        ),
        encoding="utf-8",
    )
    (outputs / "evidence.json").write_text(
        json.dumps([{"evidence_id": "ev_fin", "title": "FY2024 annual report", "source_type": "sec_filing"}]),
        encoding="utf-8",
    )
    (outputs / "canonical_metrics.json").write_text(
        json.dumps(
            {
                "metrics": [
                    {
                        "metric_name": "收入",
                        "value": 100,
                        "unit": "亿元",
                        "period": "FY2024",
                        "source_type": "sec_filing",
                        "source_evidence_id": "ev_fin",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    before = write_section_verification(outputs, markdown=markdown)

    summary = repair_failed_sections_for_outputs(
        output_dir=outputs,
        report_dir=reports,
        section_verification=before,
    )

    repaired = (reports / "report.md").read_text(encoding="utf-8")
    verification = json.loads((outputs / "section_verification.json").read_text(encoding="utf-8"))
    report_json = json.loads((reports / "report.json").read_text(encoding="utf-8"))
    assert summary["repaired"] is True
    assert summary["after_status"] == "passed"
    assert verification["status"] == "passed"
    assert "本报告分别披露相对估值与" not in repaired
    assert "估值分析待补" not in repaired
    assert "收入为100亿元" in repaired
    assert report_json["section_repair_applied"] is True


def test_section_repair_uses_quality_issues_to_rewrite_investment_conclusion(tmp_path):
    outputs = tmp_path / "outputs"
    reports = tmp_path / "reports"
    outputs.mkdir()
    reports.mkdir()
    markdown = """# 测试报告

## 执行摘要
公司财务和风险均已覆盖，报告用于质量回归。

## 财务分析
收入、利润和现金流均进入证据链。

## 估值观察
估值以收入、现金流和风险溢价为边界。

## 风险评估
风险包括需求波动、竞争压力和估值倍数回落。

## 投资结论
观察。
"""
    (reports / "report.md").write_text(markdown, encoding="utf-8")
    (reports / "report.html").write_text("<html><body>old</body></html>", encoding="utf-8")
    (reports / "report.json").write_text(json.dumps({"title": "测试报告"}), encoding="utf-8")
    (outputs / "claims.json").write_text(
        json.dumps(
            [
                {
                    "section_name": "conclusion",
                    "claim_text": "基于估值约束、现金流和风险边界，维持中性观察评级。[ev_conclusion]",
                    "evidence_ids": ["ev_conclusion"],
                }
            ]
        ),
        encoding="utf-8",
    )
    (outputs / "evidence.json").write_text(
        json.dumps([{"evidence_id": "ev_conclusion", "title": "FY2024 annual report", "source_type": "sec_filing"}]),
        encoding="utf-8",
    )
    (outputs / "canonical_metrics.json").write_text(
        json.dumps({"metrics": [{"metric_name": "revenue", "value": 100, "unit": "USD_million", "source_evidence_id": "ev_conclusion"}]}),
        encoding="utf-8",
    )
    (outputs / "quality_report.json").write_text(
        json.dumps(
            {
                "issues": [
                    {
                        "severity": "blocker",
                        "category": "professional_depth",
                        "message": "investment conclusion lacks direction and reason",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    before = {"status": "passed", "failed_sections": [], "issues": []}

    summary = repair_failed_sections_for_outputs(
        output_dir=outputs,
        report_dir=reports,
        section_verification=before,
    )

    repaired = (reports / "report.md").read_text(encoding="utf-8")
    assert summary["repaired"] is True
    assert "中性观察评级" in repaired
    assert "核心理由" in repaired
    assert "主要风险" in repaired


def test_section_repair_callback_only_changes_failed_section(tmp_path):
    outputs = tmp_path / "outputs"
    reports = tmp_path / "reports"
    outputs.mkdir()
    reports.mkdir()
    financial_body = "财务分析已有充分证据与完整解释。" * 20
    markdown = f"""# 测试报告

## 财务分析
{financial_body}

## 投资结论
短。
"""
    (reports / "report.md").write_text(markdown, encoding="utf-8")
    (reports / "report.json").write_text("{}", encoding="utf-8")
    (outputs / "section_evidence_packs.json").write_text(json.dumps({"packs": {"conclusion": {
        "must_use_evidence_ids": ["ev1"],
        "must_use_evidence": [{"evidence_id": "ev1", "period": "FY2024", "authority": "official"}],
        "unsupported_claim_ids": [],
    }}}), encoding="utf-8")

    calls = []

    def repair(payload):
        calls.append(payload["section_key"])
        assert payload["section_key"] == "conclusion"
        return {
            "section_markdown": ("维持中性判断，核心理由与风险均由正式证据支持。" * 12) + "[ev1]",
            "llm_run_id": "llm-repair-1",
        }

    summary = repair_failed_sections_for_outputs(
        output_dir=outputs,
        report_dir=reports,
        section_verification={
            "status": "failed",
            "failed_sections": ["conclusion", "investment_conclusion"],
            "issues": [],
        },
        repair_callback=repair,
    )

    repaired = (reports / "report.md").read_text(encoding="utf-8")
    assert financial_body in repaired
    assert summary["repair_strategy"] == "llm_section_rewrite"
    assert summary["evidence_ids_consumed"] == ["ev1"]
    assert calls == ["conclusion"]
    assert summary["attempts"][0]["llm_run_id"] == "llm-repair-1"
    assert summary["attempts"][0]["attempt_number"] == 1
    assert summary["attempts"][0]["status"] == "passed"


def test_section_repair_records_callback_failure_and_falls_back(tmp_path):
    outputs = tmp_path / "outputs"
    reports = tmp_path / "reports"
    outputs.mkdir()
    reports.mkdir()
    markdown = "# 测试报告\n\n## 投资结论\n短。\n"
    (reports / "report.md").write_text(markdown, encoding="utf-8")
    (reports / "report.json").write_text("{}", encoding="utf-8")

    def fail(_payload):
        raise RuntimeError("model unavailable")

    summary = repair_failed_sections_for_outputs(
        output_dir=outputs,
        report_dir=reports,
        section_verification={"status": "failed", "failed_sections": ["conclusion"], "issues": []},
        repair_callback=fail,
    )

    assert summary["repair_strategy"] == "deterministic_section_rewrite"
    assert summary["model_status"] == "failed_or_no_change"
    assert any(row.get("failure_reason") == "model unavailable" for row in summary["attempts"])
    assert [row["attempt_number"] for row in summary["attempts"] if row.get("strategy") == "llm_section_rewrite"] == [1, 2]


def test_section_repair_retries_only_failed_section_with_previous_contract_reasons(tmp_path):
    outputs = tmp_path / "outputs"
    reports = tmp_path / "reports"
    outputs.mkdir()
    reports.mkdir()
    (reports / "report.md").write_text("# 测试报告\n\n## 估值观察\n短。\n", encoding="utf-8")
    (reports / "report.json").write_text("{}", encoding="utf-8")
    (outputs / "section_evidence_packs.json").write_text(json.dumps({"packs": {"valuation": {
        "must_use_evidence_ids": ["financial-1", "market-1"],
        "must_use_evidence": [
            {"evidence_id": "financial-1", "period": "FY2024", "authority": "official"},
            {"evidence_id": "market-1", "period": "FY2024", "authority": "market_data"},
        ],
        "unsupported_claim_ids": [],
    }}}), encoding="utf-8")
    calls = []

    def repair(payload):
        calls.append(dict(payload))
        body = "估值章节基于财务数据与市场快照进行判断。" * 20
        if payload["attempt_number"] == 1:
            return {"section_markdown": body + "[financial-1]"}
        assert "must_use_evidence_not_fully_consumed" in payload["verification"]["reasons"]
        assert payload["verification"]["missing_citation_evidence_ids"] == ["market-1"]
        return {"section_markdown": body + "[financial-1][market-1]"}

    summary = repair_failed_sections_for_outputs(
        output_dir=outputs,
        report_dir=reports,
        section_verification={"status": "failed", "failed_sections": ["valuation"], "issues": []},
        repair_callback=repair,
    )

    assert len(calls) == 2
    assert [row["status"] for row in summary["attempts"]] == ["contract_failed", "passed"]
    verification = json.loads((outputs / "section_verification.json").read_text(encoding="utf-8"))
    assert verification["section_results"]["valuation"]["status"] == "passed"
    assert "valuation" not in summary["failed_sections_after"]


def test_section_repair_resolves_risk_alias_and_preserves_must_use_citation(tmp_path):
    outputs = tmp_path / "outputs"
    reports = tmp_path / "reports"
    outputs.mkdir()
    reports.mkdir()
    (reports / "report.md").write_text("# 测试报告\n\n## 风险评估\n短。\n", encoding="utf-8")
    (reports / "report.json").write_text("{}", encoding="utf-8")
    (outputs / "report_section_contracts.json").write_text(json.dumps({
        "contracts": {"risk_factors": {"title": "风险评估", "citation_evidence_ids": ["risk-1"]}}
    }), encoding="utf-8")
    (outputs / "section_evidence_packs.json").write_text(json.dumps({"packs": {"risks": {
        "must_use_evidence_ids": ["risk-1"],
        "must_use_evidence": [{"evidence_id": "risk-1", "citation_labels": ["9"]}],
        "unsupported_claim_ids": [],
    }}}), encoding="utf-8")

    def repair(payload):
        assert payload["section_key"] == "risk"
        assert payload["contract"]["citation_evidence_ids"] == ["risk-1"]
        assert payload["evidence_pack"]["must_use_evidence_ids"] == ["risk-1"]
        return {"section_markdown": "需求波动可能压缩收入增速，并通过经营杠杆影响利润率和现金流。" * 6}

    summary = repair_failed_sections_for_outputs(
        output_dir=outputs,
        report_dir=reports,
        section_verification={"status": "failed", "failed_sections": ["risks"], "issues": []},
        repair_callback=repair,
    )

    repaired = (reports / "report.md").read_text(encoding="utf-8")
    verification = json.loads((outputs / "section_verification.json").read_text(encoding="utf-8"))
    assert "[risk-1]" in repaired
    assert verification["section_results"]["risks"]["status"] == "passed"
    assert summary["evidence_ids_consumed"] == ["risk-1"]
