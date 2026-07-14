# Release Stage 3 Handoff

> Updated: 2026-07-14 (Asia/Shanghai)  
> Repository: `DeepReport-fin-workbench-v2`  
> Branch: `release/fin-research-workbench-v2`  
> Scope: continue Stage 3 runtime artifact ownership without repeating earlier audits.

## Stage 3 completion update

Stage 3 is complete on 2026-07-14. The final isolated acceptance task was:

```text
task_id: release-stage3-ready-aapl-aapl-fy2024-20260714t135156z
status: completed
quality_score: 0.9554
delivery_pass: true
machine_quality_pass: true
run_manifest.status: ready
stale_artifacts: {}
```

The report remains pending human review, so the production-baseline summary correctly reports
`formal_delivery=false`; this is not a machine-quality failure.

Final fixes included:

- Risk Claim evidence IDs from SEC Item 7A are owned by the risk section contract and appear in the final citations and bibliography.
- Objective claim-citation checks now honor explicit `citation_evidence_ids`, matching CitationBinder and Verifier behavior.
- Mixed-period evidence is detected chronologically and disclosed with its exact scope and impact when a later company-profile snapshot exists.
- Governance Claims bind to SEC proxy evidence instead of turning missing company-profile fields into unsupported governance assertions.
- All verifier and rework paths receive a complete valuation payload; the accepted AAPL artifacts pass real relative-valuation, DCF, and sensitivity arithmetic checks.

Final verification:

```text
Stage 3 focused selection: 114 passed
Report/contract/quality focused selection: 91 passed
git diff --check: passed
```

Next work is Stage 4: run clean isolated FY2024 regressions for AAPL, NVDA, and MSFT,
then expand to representative A-share and Hong Kong cases. Runtime data and secrets remain local only.

## Completed and pushed

### Stage 1

Commit: `2dd2edc fix: establish isolated release baseline`

- Isolated test Chroma from production data.
- Clean-room AAPL FY2024 report passed all machine delivery gates at `0.975`.
- Fixed SEC prior-period derivation, filing-date look-ahead, metric lineage, and checkpoint DB lifecycle.
- Focused tests: 103 passed.

### Stage 2

Commit: `7fd2ed1 refactor: remove placeholder production capabilities`

- Removed dashboard demo data and generic placeholder views.
- Removed empty graph retrieval and unsupported FAISS surface.
- Production retrieval is BM25 + local BGE dense + RRF + reranker.
- Removed fake PromptOps success and mock production data sources.
- HTTP/API/JavaScript smoke passed. Browser plugin initialization failed with `Cannot redefine property: process`, so Stage 2 did not claim screenshot acceptance.

## Stage 3 checkpoint

Goal: make LangGraph nodes own immutable upstream artifacts before Writer runs.

Target node order:

```text
official_evidence_backfill
-> evidence_gate
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
-> quality_gate
-> finalize
-> human_review
```

Implemented:

- Added explicit `prepare_write` LangGraph node.
- `prepare_write` owns critic, claim bundles, dossiers, section contracts, and phase checkpoint artifacts.
- Section evidence packs are built after pre-write artifacts exist.
- Static Writer loads persisted canonical metrics, dossiers, contracts, and section packs.
- Static Writer no longer invokes service-level evidence enhancement, canonical refresh, or section-pack rebuild.
- Added checkpoint restoration for `ReportSectionContracts`.
- Added byte-level ownership regression coverage.
- Runtime documentation now matches the actual graph order.

Focused verification at this checkpoint:

```text
49 passed
git diff --check: passed
```

Earlier Stage 3 selections also passed 30 and 65 tests respectively. The full suite remains deferred until final release acceptance.

## Real Stage 3 smoke result

Isolated task:

```text
task_id: release-stage3-aapl-fy2024-20260714
database: tmp/release_stage3_smoke_20260714/workbench.db
status: quality_failed
quality_score: 0.9291
```

The new graph nodes all executed through `prepare_write`, section-pack build, Writer, verification, repair, and quality gate. MiMo, DeepSeek, local BGE embedding, Chroma isolation, and BM25/dense/reranker retrieval were active.

Two concrete failures were found:

1. The resumed static Writer reserialized `canonical_metrics.json` after the LangGraph canonical node committed it. The byte hash changed and the run manifest correctly marked canonical metrics, claims, section packs, and report as stale. This has been fixed locally by preserving the existing canonical file during resumed phases, with a regression test using a service-style alternate JSON serialization.
2. Three market-risk claims (`cl_0021` to `cl_0023`) referenced SEC evidence IDs that were absent from final Markdown citations. Verifier therefore failed. This remains to be diagnosed at the citation binding/section repair boundary.

The old smoke artifacts remain local only and must not be committed. They still show `run_manifest.status=stale` because they were generated before the local fix.

## Immediate continuation

1. Pull this branch and restore local API/model environment variables outside Git.
2. Inspect citation ownership for `cl_0021`, `cl_0022`, and `cl_0023` across:
   - `claims.json`
   - `report_section_contracts.json`
   - `section_evidence_packs.json`
   - `citations.json`
   - `section_repair.json`
   - final `report.md`
3. Fix only the node that drops the citation. Do not weaken verifier or delivery gates.
4. Run the focused Stage 3 tests.
5. Run a fresh isolated AAPL FY2024 smoke. Do not reuse the old stale run directory.
6. Require:
   - `prepare_write` present in events/checkpoint
   - `run_manifest.status=ready`
   - no stale artifact dependencies
   - Writer leaves upstream artifact bytes unchanged
   - verifier, objective quality, and LLM review pass
   - `delivery_pass=true`
7. Complete Stage 3 with a normal commit, then continue Stage 4 multi-company US/A/H regression.

## Other-computer commands

For an existing clone:

```bash
git fetch origin
git switch release/fin-research-workbench-v2
git pull --ff-only origin release/fin-research-workbench-v2
git status --short --branch
```

For a new clone:

```bash
git clone https://github.com/wara886/DeepReport-.git DeepReport-fin-workbench-v2
cd DeepReport-fin-workbench-v2
git switch --track origin/release/fin-research-workbench-v2
```

Then tell Codex:

```text
Only work in this repository. Read docs/release_stage3_handoff_20260714.md first.
Continue Stage 3 from the citation-binding failure. Diagnose through LangGraph
events, checkpoints, run_manifest, and artifacts. Do not rerun completed Stage 1/2,
do not modify main, and do not commit runtime data.
```

Runtime SQLite, Chroma, reports, checkpoints, logs, export packages, and `.env` secrets are intentionally not synchronized by Git.

## Stage 4 US regression completion (2026-07-14)

Stage 4 US regression is complete for AAPL, NVDA, and MSFT without weakening verifier, objective-quality, LLM-review, or delivery gates.

Implemented reliability and report-semantics fixes:

- ReAct analysis observations are schema-checked; malformed ratio, trend, three-statement, peer, and valuation payloads fall back to deterministic registered tools instead of raising `KeyError('rows')`.
- Transient official-source failures are retried once. If the retry also fails, the latest validated company/period-matched official archive can be used after the normal evidence intake gate.
- Explicitly disclosed period mismatches are treated as boundary disclosures only after objective quality passes.
- Earnings bridges are rendered as net-income sensitivity, explicitly marked as non-DCF and non-equity-valuation; charts use bear/base/bull labels and no longer call net income “equity value”.
- Current market cap is expressed consistently in billions and trillions, and current-market/FY denominator mixing is stated explicitly.
- Every agent call now has a 180-second default upper bound even when no overall execution deadline is supplied.
- SEC response reading now enforces a total response deadline rather than only a per-socket inactivity timeout, preventing slow streaming responses from hanging normalization indefinitely.

Real isolated acceptance results:

```text
AAPL FY2024: completed, objective score 0.9472, delivery_pass=true
NVDA FY2024: completed, objective score 0.9494, LLM score 0.82,
             run_manifest.status=ready, stale_artifacts={}, delivery_pass=true
MSFT FY2024: completed, objective score 0.9434, LLM score 0.92,
             run_manifest.status=ready, stale_artifacts={}, delivery_pass=true
```

Verification completed during Stage 4:

```text
expanded LangGraph/agent/contract/backfill/gate/chart/data set: 178 passed
post-timeout multi-agent regression: 66 passed
SEC annual-report flow after total-response deadline: 10 passed
final focused Stage 4 fix set: 45 passed
git diff --check: passed
```

The next release step is Stage 4 A/H-share expansion using fresh isolated directories. Start with one A-share and one Hong Kong company, require the same ready manifest and all delivery gates, then proceed to the final full-suite and browser-client acceptance. Runtime acceptance directories remain local and must not be committed.
