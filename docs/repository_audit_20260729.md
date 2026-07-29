# FinSight repository audit — 2026-07-29

## Scope

- Remote/default branch: `main`
- Audited base commit: `f868e85 docs: refresh workbench showcase`
- Latest functional commit on that base: `3ed3b1e fix: complete evidence-backed report delivery`
- Local runtime data, secrets, reports, checkpoints, and vector databases remain outside Git.

## What the latest functional commit fixed

- Preserved structured financial statement metadata through repeated chunk normalization.
- Projected canonical metric winners into detailed income-statement, balance-sheet, and cash-flow tables.
- Added deterministic pre-write enrichment for official qualitative claims, financial snapshots, peers, relative valuation, and sensitivity evidence.
- Recovered bounded ReAct calls from malformed model arguments by applying validated runtime-bound arguments.
- Improved evidence candidate diversity, chart construction, valuation/peer review reconciliation, ticker false-positive filtering, and quality-remediation behavior.
- Recorded degraded agent phases explicitly and exposed shared company investment signals to task analysis.

## Regression found and fixed during this audit

The new canonical-metric node treated an empty pre-generation metric pool as fatal for every orchestrator. Injected and compatibility orchestrators create evidence during the generation callback, so the hard stop caused 19 full-suite failures across task start, artifact import, evidence gate, checkpoint resume/retry, quality gate, and lifecycle tests.

The node now enforces pre-generation canonical metrics only for the production static `MultiAgentOrchestrator`. Compatibility flows record a warning, generate their artifacts, and rebuild canonical metrics afterward. The production evidence/metric gate remains unchanged.

## Validation

```text
Affected service regression selection: 44 passed
Full suite: 1007 collected, 1005 passed, 2 optional-fixture skips, 0 failed
Python compile: passed
git diff --check: passed
```

The two skips require optional historical evaluation fixtures and are not product-code skips.

## Remaining work

### Release hardening

1. Run a fresh isolated real-data acceptance after this audit for at least one US, one A-share, and one Hong Kong annual report. Persist a sanitized machine-readable acceptance summary so README quality claims do not depend only on local ignored artifacts.
2. Confirm the new GitHub Actions matrix on Python 3.10 and 3.11 and the gated multi-architecture Docker publish after the branch is pushed.
3. Re-run browser acceptance against the fresh report database, including human review completion and formal HTML/Markdown/PDF/DOCX/CSV/JSON export.

### Runtime and data sources

1. Local workbench source-health timestamps are from 2026-07-13 and should be refreshed before being treated as current availability.
2. The last recorded local status includes missing Serper credentials, Tushare permission/quota failure, and degraded/disabled remote sources. These are environment or provider states rather than machine-quality gate regressions.
3. The local workbench database contains historical queued tasks and a large pending-review backlog. Archive test-era tasks and complete or explicitly discard pending reviews before using dashboard counts operationally.
4. Local runtime storage is sizable (approximately 1.1 GB outputs and 1.5 GB vector data); add an operator-facing retention/cleanup command before long-running deployment.

### Dependency maintenance

1. Upgrade the local environment's old `bottleneck` package used by pandas.
2. Refresh the Chroma/OpenTelemetry dependency set; new `local_rag` installs now require `grpcio>=1.63.2`, but existing environments need reinstalling.
3. Track the Starlette TestClient/httpx deprecation and jieba/pkg_resources warning for the next dependency refresh.

## Documentation changes in this audit

- Corrected Python support to 3.10+ to match `pyproject.toml` and the tested runtime.
- Documented all formal export formats and the distinction between machine delivery and completed human review.
- Distinguished core BM25/hash fallback from optional Chroma/BGE/Reranker dependencies.
- Added correct source credentials, API routes, full-suite status, optional installation commands, and known-boundary links.
- Removed configuration and health-check references for intentionally removed Metaso/Sogou backends.
- Added CI tests before Docker publication and removed deprecated `TRANSFORMERS_CACHE` configuration.
