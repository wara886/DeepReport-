import zipfile

from src.report import export_markdown_to_docx


def test_export_markdown_to_docx_creates_word_package(tmp_path):
    path = export_markdown_to_docx(
        "# Report\n\n## Executive Summary\n\n- Revenue grew with citation [ev_1].\n",
        tmp_path / "report.docx",
        title="Test Report",
        metadata={"symbol": "AAPL"},
    )

    assert path.exists()
    assert path.stat().st_size > 1024
    with zipfile.ZipFile(path, "r") as zf:
        assert "word/document.xml" in zf.namelist()
