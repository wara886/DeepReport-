from src.app.workbench_frontend import render_workbench_html


def test_workbench_ingestion_center_exposes_operable_batch_controls():
    html = render_workbench_html()

    assert "采集任务" in html
    assert "创建采集批次" in html
    assert "data-ingestion-action=\"cancel\"" in html
    assert "data-ingestion-documents" in html
    assert "查看同批次文档" in html
    assert "data-ingestion-create" in html
    assert "新建采集批次" in html
    assert 'activateView("documents")' in html
    assert "loadDocuments()" in html
