from src.tools import SkillSpec, build_financial_skill_registry


def test_financial_skill_registry_selects_planner_and_task_skills():
    registry = build_financial_skill_registry()

    planning_brief = registry.render_brief(
        query="AAPL 2025Q4 financial report with evidence, valuation, peer comparison, and verification",
        task_type="planning",
    )
    analyze_skills = registry.select(query="valuation peer margin trend", task_type="deep_analyze", max_items=2)

    assert "SkillRegistry" in planning_brief
    assert "financial_statement_analysis" in planning_brief
    assert [skill.name for skill in analyze_skills][0] == "financial_statement_analysis"
    assert "industry_research" in registry.names()
    assert "macro_context" in registry.names()


def test_financial_skill_registry_can_load_from_yaml(tmp_path):
    config = tmp_path / "skills.yaml"
    config.write_text(
        """
skills:
  - name: custom_macro
    description: Custom macro routing skill.
    agent_types: [planning, macro_research]
    trigger_terms: [macro, rates]
    tool_names: []
    input_summary: period and market evidence
    output_summary: macro brief
    guardrails:
      - Do not invent current statistics.
""".strip(),
        encoding="utf-8",
    )

    registry = build_financial_skill_registry(config_path=config)

    assert registry.names() == ["custom_macro"]
    assert registry.select(query="macro rates", task_type="macro_research")[0].name == "custom_macro"


def test_skill_registry_rejects_duplicate_names():
    registry = build_financial_skill_registry()
    duplicate = SkillSpec(name=registry.names()[0], description="duplicate")

    try:
        registry.register(duplicate)
    except ValueError as exc:
        assert "already registered" in str(exc)
    else:
        raise AssertionError("duplicate skill name should fail")
