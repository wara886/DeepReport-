# Production Path Boundary

The supported application path is:

~~~text
main.py
  -> src.app.api_fastapi
  -> ReportTaskService
  -> LangGraphReportRuntime
  -> report agents and governed tools
  -> SQLite state and versioned task artifacts
~~~

The workbench uses data/finsight_workbench.db for local business state,
data/outputs_user/runtime_checkpoints.sqlite for LangGraph checkpoints,
data/outputs_user and data/reports_user for task artifacts, and data/vector_db for
the local retrieval index.

Production retrieval uses lexical and dense candidates with an optional reranker.
The actual backend and any fallback are recorded in runtime diagnostics. Dashboard
metrics read database aggregates only and never substitute demonstration records.

Generated reports, databases, checkpoints, vector indexes, credentials, and local
reference repositories are runtime state and must remain outside source control.
Only main.py, the FastAPI application, and the ReportTaskService/LangGraph chain
define the supported product lifecycle.
