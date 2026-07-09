from src.app.workbench_frontend import render_workbench_html


def test_workbench_promptops_exposes_custom_test_inputs():
    html = render_workbench_html()

    assert "提示词运营" in html
    assert "测试输入" in html
    assert 'id="promptTestSymbol"' in html
    assert 'id="promptTestPeriod"' in html
    assert 'id="promptTestClaim"' in html
    assert 'id="promptTestEvidence"' in html
    assert "function promptTestInput" in html
    assert "manual_test_evidence" in html
    assert "task_id: taskId" in html
    assert "model_role: promptModuleValue(roleText) || \"verifier\"" in html
