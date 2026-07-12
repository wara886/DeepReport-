# Runtime Data Contracts

The runtime uses `src/schemas/runtime_contracts.py` as the normalization boundary
between acquisition, retrieval, report generation, and delivery. Adapters may
keep their source-specific fields, but every record crossing a runtime node must
also carry the versioned contracts below.

## Identity Rules

- `company_identity` owns canonical symbol, market, exchange, and currency.
- `period_spec` keeps target period and source period separate and records an
  explicit `matched`, `mismatched`, or `unknown` result.
- `document_key` identifies one source document independently of the task that
  fetched it.
- `identity_key` identifies one evidence unit within that document. Different
  chunks share a document key but have different identity keys.
- `provenance.task_id` and `provenance.run_id` isolate runtime use without
  changing the business identity of the evidence.

An upstream `evidence_id` remains available for compatibility. Deduplication and
cross-stage lineage should use `identity_key`, not a Chroma ID, database row ID,
or artifact filename.

## Authority Rules

Authority is classified from source type, verified domain, and explicit source
metadata. Search discovery alone does not upgrade a result to an official
filing. The contract records authority level, score, document type, allowed
claim types, and the classification reason.

## Metric Rules

Every canonical metric candidate carries:

- a stable `metric_id`;
- company and period contracts;
- value, unit, scale, and currency context;
- source evidence/table lineage;
- source authority.

Canonical selection must use the report target period. A candidate cannot mark
itself period-matched merely by copying the target label. Explicit validation,
filing fiscal metadata, and report dates take precedence.

## Compatibility

The v2 contracts are additive. Existing top-level fields such as `evidence_id`,
`symbol`, `period`, `source_type`, and `source_evidence_id` remain until all
legacy artifact readers are migrated. New runtime nodes must read the nested
contracts first and treat legacy fields as compatibility projections.
