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
        json.dumps({"llm_review_pass": False, "issues": [{"severity": "fatal", "message": "content is hollow and lacks valuation and peer comparison"}]}),
        encoding="utf-8",
    )
    (outputs / "delivery_gate.json").write_text(
        json.dumps(
            {
                "delivery_pass": False,
                "issue_counts": {"fatal": 1, "blocker": 1, "warning": 0, "info": 0},
                "issues": [
                    {"severity": "blocker", "category": "financial", "message": "missing balance sheet summary"},
                    {"severity": "fatal", "category": "llm_review", "message": "content is hollow; valuation and peer comparison are framework-only"},
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
    assert any("income statement" in item for item in plan["required_fixes"])
    assert any("valuation" in item for item in plan["required_fixes"])
    assert plan["quality_feedback_used"] is True
    assert paths["quality_remediation_plan"].endswith("quality_remediation_plan.json")
    assert summary["quality_feedback_used"] is True
    assert summary["quality_remediation_plan_path"].endswith("quality_remediation_plan.json")


def test_financial_gate_failures_route_to_data_and_claim_owners(tmp_path):
    outputs = tmp_path / "run" / "company" / "outputs"
    outputs.mkdir(parents=True)
    (outputs / "run_summary.json").write_text(
        json.dumps({"symbol": "TSLA", "period": "2026Q1"}),
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
        json.dumps({"llm_review_pass": False, "issues": []}),
        encoding="utf-8",
    )
    (outputs / "delivery_gate.json").write_text(
        json.dumps(
            {
                "delivery_pass": False,
                "issues": [
                    {
                        "severity": "blocker",
                        "category": "financial",
                        "message": "missing income statement, balance sheet, and cash flow summaries",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    plan = build_quality_remediation_plan(tmp_path / "run")
    agents = [item["agent"] for item in plan["responsible_agents"]]

    assert agents[:3] == ["DeepResearcherAgent", "BrowserAgent", "DeepAnalyzeAgent"]
    assert "StatementAgent" not in agents


def test_durable_memory_persists_quality_feedback_constraints(tmp_path):
    store = DurableMemoryStore(root=tmp_path / "memory")
    plan = {
        "symbol": "AMD",
        "period": "2026Q1",
        "delivery_pass": False,
        "issue_counts": {"fatal": 1, "blocker": 2},
        "memory_note": "Quality feedback for AMD 2026Q1: missing three statements",
        "planner_constraints": ["琛ラ綈涓夎〃鎽樿", "绂佹鍐嶆鍑虹幇鏆傛棤缁撹"],
        "quality_feedback_used": True,
    }

    paths = store.persist_quality_feedback(plan)
    brief = store.build_context_brief(symbol="AMD", period="2026Q1")

    assert paths["working_quality_feedback"].endswith("quality_feedback.json")
    assert "quality_feedback" in brief
    assert "琛ラ綈涓夎〃鎽樿" in brief
    assert "Do not use this as evidence" in brief
