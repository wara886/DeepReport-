# Skill Registry Design

`SkillRegistry` is a configurable capability-hint layer for planning and routing. It does not replace tools, evidence records, or verification.

## Current Role

- Skills are configured in `configs/skill_registry.yaml`.
- Planner and router can select relevant skills based on the research task.
- Rendered skill briefs describe expected inputs, outputs, tools and guardrails.
- Tool invocation remains owned by the executing agent and registered tool boundary.

## Included Capability Groups

| Skill | Intended use |
| --- | --- |
| `evidence_discovery` | Find filings, market snapshots and evidence candidates. |
| `financial_statement_analysis` | Build financial views, metrics and valuation context. |
| `report_assembly` | Compose cited report output and charts. |
| `verification_rework` | Check support and route unresolved gaps. |
| `industry_research` | Assemble bounded industry context where evidence permits. |
| `macro_context` | Add evidence-bounded macro transmission context. |

## Guardrails

- Skill text is prompt context, not proof of execution.
- Historical context cannot be promoted to factual evidence.
- Unsupported numbers fail verification even when the selected skill suggests financial analysis.
