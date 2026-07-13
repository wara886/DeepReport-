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
    assert "草稿生成" in html
    assert "正式交付" in html
    assert "待补权威来源" in html
    assert "不应作为正式研报交付" in html
    assert "检查数据源" in html
    assert "补采集批次" in html


def test_workbench_uses_unified_delivery_readiness():
    html = render_workbench_html()

    assert "taskDeliveryStatus" in html
    assert '["failed", "timeout", "cancelled", "archived"].includes(lifecycleStatus)' in html
    assert "renderDeliveryReadiness" in html
    assert "统一交付状态" in html
    assert "can_generate_draft" in html
    assert "can_enter_human_review" in html
    assert "can_deliver_formal_report" in html
    assert "can_export_formal_package" in html
    assert "尚未完成证据检查" in html
    assert "存在待复核主张" in html
    assert "resume_runtime" in html
    assert "retry_checkpoint" in html
    assert "runtime/resume" in html
    assert "runtime/retry" in html
    assert "复核完成，继续工作流" in html
    assert "从失败节点继续" in html


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
    assert "报告引用证据链" in html
    assert "证据链路：报告结论 → 主张复核" in html
    assert "缺引用主张" in html
    assert "关联证据：" in html
    assert "未进入正文的引用" in html
    assert "sourceDisplayText" in html
    assert "productText" in html
    assert "查看报告产物" in html


def test_workbench_report_task_entity_memory_is_productized():
    html = render_workbench_html()

    assert "renderTaskEntityMemory" in html
    assert "bindTaskEntityMemoryButtons" in html
    assert "extractEntitiesFromTask" in html
    assert "/api/entities/extract-from-task" in html
    assert "结构化记忆" in html
    assert "沉淀当前任务证据" in html
    assert "已沉淀实体" in html
    assert "已形成关系" in html
    assert "实体样例" in html
    assert "关系样例" in html
    assert "证据支持" in html
    assert "数据进入、记忆沉淀、结构化处理、线索发现、主张复核、报告输出" in html


def test_workbench_report_task_signal_closure_is_productized():
    html = render_workbench_html()

    assert "renderTaskSignalSummary" in html
    assert "bindTaskSignalButtons" in html
    assert "generateSignalsForTask" in html
    assert "/api/investment-signals/generate" in html
    assert "投资线索闭环" in html
    assert "生成当前任务线索" in html
    assert "线索研判摘要" in html
    assert "研判优先级" in html
    assert "建议动作" in html
    assert "仅供研究，不构成投资建议" in html
    assert "activeSignalTaskScope" in html
    assert "data-signal-task-id" in html
    assert "当前仅查看该研报任务的线索" in html


def test_workbench_report_task_argument_and_risk_chain_are_productized():
    html = render_workbench_html()

    assert "renderArgumentFlow" in html
    assert "renderRiskPaths" in html
    assert "投资逻辑链" in html
    assert "风险传导链" in html
    assert "实体" in html
    assert "事件" in html
    assert "财务事实" in html
    assert "投资线索" in html
    assert "Claim" in html
    assert "报告章节" in html
    assert "链路缺口" in html
    assert "证据已绑定" in html
    assert "支撑待补齐" in html
    assert "已绑定财务事实" in html
    assert "闭环进度" in html
    assert "支撑绑定" in html
    assert "该风险还没有承接到研报主张" in html
