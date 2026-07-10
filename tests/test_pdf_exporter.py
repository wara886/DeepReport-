from src.report import export_markdown_to_pdf


def test_export_markdown_to_pdf_creates_renderable_a4_report(tmp_path):
    path = export_markdown_to_pdf(
        "# 贵州茅台研究报告\n\n## 执行摘要\n\n- 收入保持稳健增长。[ev_1]\n\n## 风险评估\n\n渠道库存需要持续跟踪。",
        tmp_path / "report.pdf",
        title="贵州茅台 FY2025 金融研究报告",
        metadata={"task_id": "task-pdf", "quality_score": 0.92},
    )

    assert path.read_bytes().startswith(b"%PDF")
    assert path.stat().st_size > 2_000

    import fitz

    document = fitz.open(path)
    assert document.page_count >= 1
    pixmap = document[0].get_pixmap(matrix=fitz.Matrix(1.2, 1.2), alpha=False)
    assert pixmap.width > 500
    assert pixmap.height > 700
    assert len(pixmap.samples) > 100_000
