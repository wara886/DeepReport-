from src.app.workbench_frontend import render_workbench_html


def test_workbench_evaluation_center_is_productized_and_loads_api():
    html = render_workbench_html()

    assert 'data-view="evaluation"' in html
    assert "评测中心" in html
    assert "研报质量、证据覆盖、模型运行和失败原因" in html
    assert "/api/evaluation/summary" in html
    assert "交付通过率" in html
    assert "引用支持率" in html
    assert "模型运行成功率" in html
    assert "最近研报质量" in html
    assert "单任务诊断" in html
    assert "data-evaluation-diagnostic" in html
    assert "/api/evaluation/report-tasks/" in html
    assert "/api/report-tasks/${encodeURIComponent(taskId)}/analysis" in html
    assert "loadEvaluationTaskDiagnostic" in html
    assert "分析链路摘要" in html
    assert "打开完整分析包" in html
    assert "renderEvaluationAnalysisLinkage" in html
    assert "loadEvaluation" in html
    assert 'data-view="evaluation"><span>评测中心</span><span class="tag preview">预览</span></button>' in html
