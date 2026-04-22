# eval_v1

Stage 12 fixed evaluation set for local regression and cloud-train prechecks.

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

## Notes

- `gold_numeric_facts` currently keeps metric slots for `revenue`, `net_income`, `yoy`, `gross_margin`.
- Initial seeded values use `"unknown"` placeholders and should be refined through annotation passes.
- Keep `cases.jsonl` stable once a regression baseline is frozen.
