from src.report.html_report_generator import render_professional_html_report


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
    assert "References" in html


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
