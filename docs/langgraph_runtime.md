# LangGraph Report Runtime

LangGraph is the report control plane. Generated files remain data artifacts;
they must not implicitly decide which processing step runs next.

## Node Order

```text
evidence
-> generation
-> inspect_agent_execution
-> official_evidence_backfill
-> build_canonical_metrics
-> build_section_evidence_packs
-> verify_sections
-> repair_failed_sections
-> quality
-> finalize
-> optional human_review
```

Generation runs before artifact-dependent nodes because contracts, dossiers,
tables, metrics, claims, and agent traces do not exist before the orchestrator
has produced its initial artifacts. Official backfill runs before canonical
metric selection so newly acquired tables can participate in arbitration.

## Execution Ownership

- `generation` calls the orchestrator once and imports its initial projection.
- `inspect_agent_execution` reads the collaboration, model, and tool traces and
  records failed agents/tools with a deterministic root cause.
- Official backfill and canonical metric refresh are not repeated inside the
  generation callback.
- Quality may import artifacts again because it projects new verification and
  delivery artifacts; this is synchronization, not repeated generation.
- Every node has its own checkpoint. Retrying a failed canonical or quality
  node does not rerun completed generation.

The current orchestrator still executes several internal agent roles during the
generation node. The execution inspection artifact makes those roles visible;
the next report-quality phase can promote section drafting and repair into
separate controllable nodes without changing evidence identity or task state.
