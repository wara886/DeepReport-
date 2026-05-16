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
                "chart_js": {"type": "bar", "labels": ["营收"], "data": [126.3], "label": "指标值"},
            }
        ],
        citations=[{"evidence_id": "ev1"}],
    )

    assert "https://cdn.jsdelivr.net/npm/chart.js" in html
    assert '<div class="chart-frame"><canvas id="canvas_c1"></canvas></div>' in html
    assert "height: 320px" in html
    assert "<h2>执行摘要</h2>" in html
    assert "参考来源 1 条" in html
