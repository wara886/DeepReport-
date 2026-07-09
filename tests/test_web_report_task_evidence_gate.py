from src.app.workbench_frontend import render_workbench_html


def test_workbench_report_task_evidence_gate_is_productized():
    html = render_workbench_html()

    assert 'id="taskEvidenceGateInput"' in html
    assert "生成前证据门禁" in html
    assert "证据不足时暂停生成" in html
    assert "证据不足时继续并标记风险" in html
    assert "跳过生成前证据检查" in html
    assert "enforce_evidence_gate" in html
    assert "allow_weak_evidence" in html
    assert "skip_evidence_gate" in html
    assert "renderPreGenerationEvidenceGate" in html
    assert "证据不足，已暂停生成" in html
    assert "未通过，已暂停生成" in html
    assert "检查数据源" in html
    assert "补采集批次" in html


def test_workbench_report_task_retrieval_diagnostics_is_productized():
    html = render_workbench_html()

    assert "renderRetrievalDiagnostics" in html
    assert "证据召回诊断" in html
    assert "诊断阶段" in html
    assert "候选资料" in html
    assert "命中证据" in html
    assert "来源缺口" in html
    assert "查询口径" in html
    assert "候选资料样例" in html
    assert "期间或查询条件未命中" in html
    assert "缺少必要权威来源" in html


def test_workbench_report_task_citation_usage_is_productized():
    html = render_workbench_html()

    assert "renderCitationUsage" in html
    assert "引用覆盖闭环" in html
    assert "引用闭环已形成" in html
    assert "正文引用待补齐" in html
    assert "正文已使用引用" in html
    assert "可追溯主张" in html
    assert "缺引用主张" in html
    assert "未进入正文的引用" in html
    assert "查看报告产物" in html
