from src.report.html_report_generator import render_professional_html_report
from src.report.report_enhancer import attach_charts_to_html, attach_charts_to_markdown, render_chart_html


def test_professional_html_report_embeds_chartjs_payload():
    html = render_professional_html_report(
        markdown="# 报告\n\n## 执行摘要\n\n正文\n\n## 图表\n\n![关键指标](x.png)\n\n## 参考来源\n\n- [ev1] 来源",
        title="测试报告",
        charts=[
            {
                "chart_id": "c1",
                "title": "关键指标",
                "source_fields": "claims.numeric_values",
                "chart_js": {"type": "bar", "labels": ["营收", "净利润"], "data": [126.3, 31.2], "label": "指标值"},
            }
        ],
        citations=[{"evidence_id": "ev1"}],
    )

    assert "https://cdn.jsdelivr.net/npm/chart.js" in html
    assert '<div class="chart-container"><canvas id="canvas-c1" ondblclick="downloadChart(this)"></canvas></div>' in html
    assert "height: 400px" in html
    assert "chartjs-plugin-datalabels" in html
    assert "ChartDataLabels" in html
    assert "<h2>" in html
    assert "参考来源" in html


def test_quality_blocked_chinese_report_is_labeled_as_draft_blocked():
    html = render_professional_html_report(
        markdown="# 测试报告\n\n## 执行摘要\n\n本节暂不展开详细分析。",
        title="测试报告",
        delivery_status="blocked_quality_gate_failed",
        quality_blocked=True,
        top_blockers=["执行摘要过短", "估值章节截断"],
    )

    assert "草稿研报（正式交付阻塞）" in html
    assert "草稿生成，正式交付阻塞" in html
    assert "当前报告为草稿版本" in html
    assert "正常生成" not in html


def test_chart_tabs_are_self_contained():
    """Chart tabs use custom data attributes and lazy render, no Bootstrap tab dependency."""
    html = render_professional_html_report(
        markdown="# 报告\n\n## 执行摘要\n\n正文\n\n## 图表\n\n![关键指标](x.png)\n\n## 参考来源\n\n- [ev1] 来源",
        title="测试报告",
        charts=[
            {"chart_id": "c1", "title": "关键指标", "source_fields": "claims.numeric_values",
             "chart_js": {"type": "bar", "labels": ["营收", "净利润"], "data": [126.3, 31.2], "label": "指标值"}},
            {"chart_id": "c2", "title": "结论置信度", "source_fields": "claims.confidence",
             "chart_js": {"type": "bar", "labels": ["claim_1", "claim_2"], "data": [0.85, 0.78], "label": "置信度"}},
        ],
        citations=[],
    )

    assert 'data-chart-tab="c1"' in html
    assert 'data-chart-pane="c1"' in html
    assert 'data-chart-pane="c2"' in html
    assert 'data-bs-toggle="tab"' not in html
    assert "initFinSightChartTabs" in html
    assert "ensureChartRendered" in html
    assert "window.finSightCharts" in html
    assert "chartConfig" in html
    assert 'typeof ChartDataLabels' in html


def test_chart_tabs_horizontal_css():
    """Chart tabs must use horizontal flexbox layout."""
    html = render_professional_html_report(
        markdown="# 报告\n\n## 执行摘要\n\n正文\n\n## 图表\n\n![关键指标](x.png)",
        title="测试报告",
        charts=[
            {"chart_id": "c1", "title": "关键指标", "source_fields": "claims.numeric_values",
             "chart_js": {"type": "bar", "labels": ["营收", "净利润"], "data": [126.3, 31.2], "label": "指标值"}},
        ],
        citations=[],
    )

    assert "display: flex" in html
    assert "flex-direction: row" in html
    assert "flex-wrap: wrap" in html
    assert ".chart-tabs" in html


def test_professional_html_uses_clean_chinese_chart_labels_and_units():
    html = render_professional_html_report(
        markdown="# 贵州茅台 2026Q1 研报\n\n## 图表\n\n![财务规模](x.png)",
        title="贵州茅台 2026Q1 研报",
        charts=[
            {
                "chart_id": "financial_scale_bar",
                "title": "财务规模",
                "chart_js": {
                    "type": "bar",
                    "labels": ["收入", "净利润", "经营现金流"],
                    "data": [1720.5, 823.2, 615.2],
                    "label": "亿元人民币",
                    "unit_label": "亿元人民币",
                },
            }
        ],
        citations=[{"evidence_id": "ev1", "title": "公告"}],
    )

    assert "交互图表" in html
    assert "chartPayloads" in html
    assert '"unit_label": "亿元人民币"' in html
    assert "收入" in html
    assert "净利润" in html
    assert "经营现金流" in html


def test_empty_static_chart_section_is_removed_from_markdown():
    markdown = "# 报告\n\n## 执行摘要\n\n正文\n\n## 图表\n\n- 暂无图表。"

    result = attach_charts_to_markdown(markdown, [])

    assert "## 图表" not in result
    assert "暂无图表" not in result
    assert "## 执行摘要" in result


def test_static_chart_html_is_skipped_when_no_visible_charts():
    html = "<html><body><main>正文</main></body></html>"

    result = attach_charts_to_html(html, [])

    assert result == html
    assert render_chart_html([]) == ""
    assert "report-charts" not in result


def test_static_chart_html_is_not_appended_after_interactive_charts():
    html = "<html><body><section><h2>交互图表</h2><script>var chartPayloads = [];</script></section></body></html>"
    charts = [{"chart_id": "c1", "title": "关键指标", "output_path": "data/outputs_user/runs/r1/outputs/charts/c1.png"}]

    result = attach_charts_to_html(html, charts)

    assert result == html
    assert "report-charts" not in result
