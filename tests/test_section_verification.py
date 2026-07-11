import json

from src.evaluation.section_verification import build_section_verification, write_section_verification


def _full_report(section_body: str | None = None) -> str:
    body = section_body or (
        "本节基于官方披露、结构化指标和可核验证据展开。公司收入、盈利质量、现金流和风险事项均有明确来源支撑，"
        "并与估值和投资结论保持一致。分析避免模板化判断，明确说明驱动因素、约束条件和后续需要跟踪的关键变量。"
        "同时说明关键指标的期间、单位和来源等级，区分已经验证的事实、合理推断和需要人工复核的风险点，"
        "确保正文不是泛化描述，而是能够支撑正式交付判断的业务分析。"
    )
    return "\n\n".join(
        [
            "# 测试研报",
            f"## 执行摘要\n\n{body}",
            f"## 业务概览\n\n{body}业务结构、区域收入、客户结构和竞争优势均已展开说明。",
            f"## 财务分析\n\n{body}收入、毛利率、费用率、净利润、经营现金流、资产负债和资本开支均有交叉解释，并说明同比、环比和利润率变化的业务原因。",
            f"## 估值观察\n\n{body}相对估值、盈利质量、市场预期和估值敏感性均形成可复核判断。",
            f"## 风险评估\n\n{body}主要风险包括需求波动、成本压力、监管披露、现金流波动和估值回撤。",
            f"## 投资结论\n\n{body}结论给出偏中性的正式观点、三条证据支撑理由和两个需要持续跟踪的风险。",
        ]
    )


def test_section_verification_passes_clean_core_sections():
    artifact = build_section_verification(markdown=_full_report())

    assert artifact["status"] == "passed"
    assert artifact["formal_delivery_allowed"] is True
    assert artifact["failed_sections"] == []


def test_section_verification_blocks_missing_and_short_sections():
    artifact = build_section_verification(markdown="# 报告\n\n## 执行摘要\n\n太短。")

    assert artifact["status"] == "failed"
    assert artifact["formal_delivery_allowed"] is False
    assert "executive_summary" in artifact["failed_sections"]
    assert "financial_analysis" in artifact["failed_sections"]
    assert any(issue["category"] == "section_contract" for issue in artifact["issues"])


def test_section_verification_blocks_placeholder_and_unfinished_tail():
    artifact = build_section_verification(markdown=_full_report("本节暂不展开详细分析，本报告分别披露"))

    assert artifact["status"] == "failed"
    assert "executive_summary" in artifact["failed_sections"]
    reasons = artifact["section_results"]["executive_summary"]["reasons"]
    assert "placeholder_text" in reasons
    assert "unfinished_sentence_tail" in reasons


def test_section_verification_blocks_contract_gaps_and_writes_artifact(tmp_path):
    output_dir = tmp_path / "outputs"
    artifact = write_section_verification(
        output_dir,
        markdown=_full_report(),
        report_section_contracts={
            "contracts": {
                "valuation": {
                    "status": "gap",
                    "blocked_reasons": ["missing official valuation basis"],
                }
            }
        },
        quality_remediation_plan={"failed_sections": ["risks"]},
    )

    parsed = json.loads((output_dir / "section_verification.json").read_text(encoding="utf-8"))
    assert artifact["status"] == "failed"
    assert parsed["failed_sections"] == ["risks", "valuation"]
    assert any(issue["source"] == "quality_remediation_plan" for issue in parsed["issues"])
