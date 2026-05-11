# eval_v1

Stage 12 fixed evaluation set for local regression and cloud-train prechecks.
The current v1 scope is company/stock reports only; macro and industry report
types are intentionally out of scope until the company path is stable.

## Files

- `cases.jsonl`: frozen evaluation cases (seeded to 30 cases, can expand to 50+).
- `schema.json`: contract for each case record.

## Required Fields

Each JSONL line includes at least:

- `case_id`
- `query`
- `task_type` (`fundamental|financial|event`)
- `source_scope`
- `gold_claims`
- `gold_evidence_ids`
- `gold_numeric_facts`
- `allow_fallback`

This project also keeps `symbol` and `period` to map each case to real local data folders.

## Quality Contract

- `gold_numeric_facts` keeps canonical metric slots for `revenue`, `net_income`, `yoy`, `gross_margin`.
- Gold values should be concrete numbers, not `"unknown"`.
- `gold_claims` should be human-readable Chinese/English claims tied to canonical facts, not template placeholders.
- `gold_evidence_ids` may use logical source tags such as `AAPL:2025Q4:financials`; regression summarization maps these to source types for top-k hit checks.
- Run `audit_eval_v1_cases(...)` before freezing a new baseline to catch placeholder claims, unknown numeric facts, duplicate case IDs, and missing raw source files.
- Keep `cases.jsonl` stable once a regression baseline is frozen.
