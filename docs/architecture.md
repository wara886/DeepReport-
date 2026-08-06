# FinSight Architecture

FinSight is an evidence-driven financial research workbench. The public runtime
separates data acquisition, evidence governance, report generation, verification,
and human review so that failures can be located at a specific node.

## Runtime Flow

~~~mermaid
flowchart LR
    UI["Web workbench"] --> API["FastAPI"]
    API --> TASK["ReportTaskService"]
    TASK --> GRAPH["LangGraph runtime"]

    subgraph PIPELINE["Checkpointed report pipeline"]
      BACKFILL["Official evidence backfill"] --> GATE["Evidence gate"]
      GATE --> PLAN["Planning"]
      PLAN --> RESEARCH["Research and bounded ReAct"]
      RESEARCH --> NORMALIZE["Evidence normalization"]
      NORMALIZE --> ANALYZE["Financial analysis"]
      ANALYZE --> METRICS["Canonical metrics"]
      METRICS --> PACKS["Section evidence packs"]
      PACKS --> WRITE["Section writing"]
      WRITE --> VERIFY["Report and section verification"]
      VERIFY --> REPAIR["Targeted section repair"]
      REPAIR --> QUALITY["Delivery quality gate"]
      QUALITY --> REVIEW["Human claim review"]
    end

    GRAPH --> BACKFILL
    DB[("SQLite business state")] <--> TASK
    CHECKPOINT[("SQLite checkpoints")] <--> GRAPH
    VECTOR[("Task-isolated vector index")] <--> RESEARCH
    ARTIFACTS[("Versioned artifacts")] <--> METRICS
    ARTIFACTS <--> PACKS
    ARTIFACTS <--> WRITE
    ARTIFACTS <--> VERIFY
~~~

## Ownership Boundaries

- FastAPI owns the HTTP contract and serves the workbench.
- ReportTaskService owns task lifecycle, persistence, artifact registration, and
  product-facing status projection.
- LangGraph owns node order, checkpoints, retry boundaries, and human-review
  interruption.
- Research agents may call only the Tool Registry subset granted by the current
  task. Runtime-bound company, period, and storage arguments override model input.
- Canonical Metrics owns the formal value, currency, unit, period, source, and
  derivation lineage used by writing, charts, valuation, and verification.
- Section Evidence Packs own the evidence that each report section may and must
  consume.
- Delivery readiness is calculated from evidence, metrics, section contracts,
  citations, numeric consistency, verifier output, model review, and human review.

## Persistence

SQLite stores business entities and LangGraph checkpoints for the local product.
Generated evidence, metrics, claims, citations, reports, charts, and manifests are
stored as task-scoped files. The local vector index is isolated by task, company,
and report period to prevent cross-task evidence leakage.

## Failure Localization

Every graph node records start and completion state, elapsed time, retry count,
errors, and output artifacts. A failed research node can be retried without
rewriting the report; a failed report section is repaired without rerunning data
collection. Upstream artifact changes invalidate dependent report versions.

## Deployment

main.py starts the user application. Docker uses the same entrypoint and exposes
the health endpoint before publishing the workbench. Runtime secrets and generated
user data remain outside source control.
