from pathlib import Path

from src.tracing.writer_trace import (
    WriterTraceEvent,
    aggregate_writer_trace,
    append_writer_trace,
    export_writer_trace_csv,
    read_writer_trace,
)


def test_writer_trace_roundtrip_and_aggregate(tmp_path: Path):
    trace_path = tmp_path / "writer_trace.jsonl"
    append_writer_trace(
        trace_path,
        WriterTraceEvent(
            case_id="c1",
            query="q1",
            task_type="financial",
            retrieved_doc_count=5,
            reranked_topk_ids=["a", "b"],
            evidence_coverage=0.8,
            verifier_accept_rate=0.7,
            writer_mode="normal",
            fallback_reason="none",
            final_report_path="reports/r1.md",
        ),
    )
    append_writer_trace(
        trace_path,
        WriterTraceEvent(
            case_id="c2",
            query="q2",
            task_type="financial",
            retrieved_doc_count=5,
            reranked_topk_ids=["c"],
            evidence_coverage=0.5,
            verifier_accept_rate=0.4,
            writer_mode="fallback",
            fallback_reason="timeout_retry",
            final_report_path="reports/r2.md",
        ),
    )
    rows = read_writer_trace(trace_path)
    summary = aggregate_writer_trace(rows, group_key="task_type")
    assert len(rows) == 2
    assert summary["financial"]["fallback_rate"] == 0.5

    csv_path = export_writer_trace_csv(rows, tmp_path / "writer_trace.csv")
    assert csv_path.exists()

