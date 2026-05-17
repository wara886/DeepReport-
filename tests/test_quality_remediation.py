import json

from src.agents.durable_memory import DurableMemoryStore
from src.evaluation.quality_remediation import build_quality_remediation_plan, write_quality_remediation_plan


def test_quality_remediation_plan_collects_gate_issues_and_updates_summary(tmp_path):
    outputs = tmp_path / "run" / "company" / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "run_summary.json").write_text(
        json.dumps({"symbol": "AMD", "period": "2026Q1"}),
        encoding="utf-8",
    )
    (outputs / "quality_report.json").write_text(
        json.dumps(
            {
                "objective_pass": False,
                "required_checks": {"passed": False, "details": {"has_three_table_summary": False}},
            }
        ),
        encoding="utf-8",
    )
    (outputs / "llm_quality_review.json").write_text(
        json.dumps({"llm_review_pass": False, "issues": [{"severity": "fatal", "message": "内容空洞，缺少估值和同行对比"}]}),
        encoding="utf-8",
    )
    (outputs / "delivery_gate.json").write_text(
        json.dumps(
            {
                "delivery_pass": False,
                "issue_counts": {"fatal": 1, "blocker": 1, "warning": 0, "info": 0},
                "issues": [
                    {"severity": "blocker", "category": "financial", "message": "缺少资产负债表摘要"},
                    {"severity": "fatal", "category": "llm_review", "message": "内容空洞，估值和同行对比只有框架"},
                ],
            }
        ),
        encoding="utf-8",
    )

    plan = build_quality_remediation_plan(tmp_path / "run")
    paths = write_quality_remediation_plan(tmp_path / "run", plan)
    summary = json.loads((outputs / "run_summary.json").read_text(encoding="utf-8"))

    assert "three_statement_analysis" in plan["failed_sections"]
    assert "valuation" in plan["failed_sections"]
    assert any("三表摘要" in item for item in plan["required_fixes"])
    assert any("估值" in item for item in plan["required_fixes"])
    assert plan["quality_feedback_used"] is True
    assert paths["quality_remediation_plan"].endswith("quality_remediation_plan.json")
    assert summary["quality_feedback_used"] is True
    assert summary["quality_remediation_plan_path"].endswith("quality_remediation_plan.json")


def test_durable_memory_persists_quality_feedback_constraints(tmp_path):
    store = DurableMemoryStore(root=tmp_path / "memory")
    plan = {
        "symbol": "AMD",
        "period": "2026Q1",
        "delivery_pass": False,
        "issue_counts": {"fatal": 1, "blocker": 2},
        "memory_note": "Quality feedback for AMD 2026Q1: missing three statements",
        "planner_constraints": ["补齐三表摘要", "禁止再次出现暂无结论"],
        "quality_feedback_used": True,
    }

    paths = store.persist_quality_feedback(plan)
    brief = store.build_context_brief(symbol="AMD", period="2026Q1")

    assert paths["working_quality_feedback"].endswith("quality_feedback.json")
    assert "quality_feedback" in brief
    assert "补齐三表摘要" in brief
    assert "Do not use this as evidence" in brief
