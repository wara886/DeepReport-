# LangGraph Report Runtime

LangGraph is the report control plane. Generated files remain data artifacts;
they must not implicitly decide which processing step runs next.

## Node Order

```text
official_evidence_backfill
-> evidence
-> planning
-> research
-> normalize_evidence
-> analyze
-> build_canonical_metrics
-> prepare_write
-> build_section_evidence_packs
-> write_report
-> verify_report
-> inspect_agent_execution
-> verify_sections
-> repair_failed_sections
-> quality
-> finalize
-> optional human_review
```

Official backfill runs before evidence gating. Research and analysis then create
the normalized evidence, raw metric candidates, tables, and claims. Canonical
metric arbitration is committed before any writing preparation.

`prepare_write` owns the pre-write critic, claim-evidence bundles, section
dossiers, section contracts, and citation binding. The next node materializes
the section evidence packs from those persisted inputs. `write_report` consumes
that exact checkpoint and must not rebuild or mutate evidence, canonical
metrics, claims, dossiers, contracts, or section packs.

## Execution Ownership

- Planning, research, normalization, analysis, pre-write preparation, and report
  writing have independent LangGraph checkpoints.
- `build_canonical_metrics` owns `canonical_metrics.json`.
- `prepare_write` owns `pre_write_critic.json`, `claim_evidence_bundles.json`,
  `section_dossiers.json`, and `report_section_contracts.json`.
- `build_section_evidence_packs` owns `section_evidence_packs.json`.
- `write_report` owns citations and report files. On the static production path
  it commits only those downstream artifacts.
- `inspect_agent_execution` reads the collaboration, model, and tool traces and
  records failed agents/tools with a deterministic root cause.
- The compatibility path for injected legacy orchestrators may still normalize
  their all-in-one output after generation; it is not the production path.
- Quality may import artifacts again because it projects new verification and
  delivery artifacts; this is synchronization, not repeated generation.
- Every node has its own checkpoint. Retrying Writer does not rerun research,
  analysis, canonical arbitration, or pre-write preparation.

The run manifest stores content versions and dependency versions. Tests assert
that Writer leaves all upstream pre-write artifacts byte-for-byte unchanged.
