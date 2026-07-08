from src.app.workbench_frontend import render_workbench_html


def test_workbench_llm_run_detail_exposes_harness_metadata():
    html = render_workbench_html()

    assert "LLM 调用详情" in html
    assert "item.metadata" in html
    assert "<h3>元数据</h3>" in html
    assert "/api/llm-runs/" in html
    assert "bindPromptTestButtons" in html
    assert "boundPromptTest" in html
