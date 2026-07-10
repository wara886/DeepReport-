from src.app.workbench_frontend import render_workbench_html


def test_workbench_evaluation_center_is_productized_and_loads_api():
    html = render_workbench_html()

    assert 'data-view="evaluation"' in html
    assert "评测中心" in html
    assert "研报质量、证据覆盖、模型运行和失败原因" in html
    assert "/api/evaluation/summary" in html
    assert "交付通过率" in html
    assert "已质检任务" in html
    assert "已进入质检任务均值" in html
    assert "引用支持率" in html
    assert "模型运行成功率" in html
    assert "最近研报质量" in html
    assert "回归矩阵" in html
    assert "evaluationRegressionMatrix" in html
    assert "renderEvaluationRegressionMatrix" in html
    assert "regression_matrix" in html
    assert "regressionStatusText" in html
    assert "按任务检查交付门禁、证据覆盖、引用支持和数字一致性" in html
    assert "单任务诊断" in html
    assert "data-evaluation-diagnostic" in html
    assert "/api/evaluation/report-tasks/" in html
    assert "/api/report-tasks/${encodeURIComponent(taskId)}/analysis" in html
    assert "loadEvaluationTaskDiagnostic" in html
    assert "分析链路摘要" in html
    assert "打开完整分析包" in html
    assert "renderEvaluationAnalysisLinkage" in html
    assert "证据召回准备度" in html
    assert "renderRetrievalCoverage" in html
    assert "证据召回质量" in html
    assert "证据召回可用率" in html
    assert "关键来源覆盖率" in html
    assert "renderEvaluationRetrievalQuality" in html
    assert "数据源与采集健康" in html
    assert "renderDiagnosticDataSourceHealth" in html
    assert "data-datasource-query" in html
    assert "data-ingestion-source" in html
    assert "创建补采集批次" in html
    assert "data-remediation-batch" in html
    assert "createRemediationBatch" in html
    assert "$(\"ingestionSource\").dataset.sourceKey = created.source_key || \"\"" in html
    assert "sourceInput.dataset.sourceKey" in html
    assert "showNotice(`已创建补采集批次：" in html
    assert "function systemInfoTitle" in html
    assert "技术追踪信息" in html
    assert "任务追踪号" in html
    assert "来源追踪号" in html
    assert "loadEvaluation" in html
    assert 'data-view="evaluation"><span>评测中心</span><span class="tag preview">预览</span></button>' in html


def test_workbench_p1_closure_copy_and_task_linkage_are_productized():
    html = render_workbench_html()

    assert "分析链路总览" in html
    assert "数据进入、记忆沉淀、结构化处理、线索发现、主张复核、报告输出" in html
    assert "为什么是这个质量分" in html
    assert "还差什么" in html
    assert "查看主张复核" in html
    assert "进入评测中心" in html
    assert "尚未沉淀证据" in html
    assert "主张通常来自研报产物导入" in html
    assert "示意分布不代表当前空间真实数据" in html
    assert "带有黄色提示的图表不计入真实 KPI" in html
    assert "renderTaskLinkageOverview" in html
    assert "documentEvidenceEmptyState" in html
