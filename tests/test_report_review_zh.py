from __future__ import annotations

from pathlib import Path

from src.evaluation.report_review_zh import generate_report_review_zh


def test_generate_report_review_zh_for_eval_case() -> None:
    project_root = Path(__file__).resolve().parents[1]
    report_md = (
        project_root
        / "data"
        / "evaluation"
        / "eval_v1"
        / "runs"
        / "AAPL"
        / "2025Q4"
        / "bm25_real_writer"
        / "reports"
        / "report.md"
    )
    assert report_md.exists()

    outputs = generate_report_review_zh(report_md_path=report_md, project_root=project_root)

    review_md = Path(outputs["report_review_zh_md"])
    summary_md = Path(outputs["review_focus_summary_md"])
    assert review_md.exists()
    assert summary_md.exists()
    assert "人工审核中文视图" in review_md.read_text(encoding="utf-8")
    assert "中文审核摘要" in summary_md.read_text(encoding="utf-8")
