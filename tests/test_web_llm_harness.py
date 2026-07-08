from src.app.workbench_frontend import render_workbench_html


def test_workbench_llm_run_detail_exposes_harness_metadata():
    html = render_workbench_html()

    assert "智能体运行详情" in html
    assert "item.metadata" in html
    assert "<summary>运行诊断</summary>" in html
    assert "/api/llm-runs/" in html
    assert "bindPromptTestButtons" in html
    assert "boundPromptTest" in html
