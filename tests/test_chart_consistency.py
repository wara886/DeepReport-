from src.report.chart_consistency import audit_chart_consistency


def test_chart_consistency_passes_traceable_chart():
    result = audit_chart_consistency(
        charts=[
            {
                "chart_id": "key_metrics_bar",
                "title": "关键指标",
                "source_fields": "claims.numeric_values",
                "chart_js": {"labels": ["revenue"], "data": [126.3]},
            }
        ],
        claims=[{"claim_id": "cl1", "numeric_values": {"revenue_billion": 126.3}}],
        evidence_records=[],
        markdown="# 报告\n\n## 图表\n\n![关键指标](x.png)",
    )

    assert result["passed"] is True
    assert result["failed_chart_count"] == 0


def test_chart_consistency_flags_empty_and_unreferenced_chart():
    result = audit_chart_consistency(
        charts=[
            {
                "chart_id": "orphan",
                "title": "孤立图表",
                "source_fields": "claims.numeric_values",
                "chart_js": {"labels": [], "data": []},
            }
        ],
        claims=[{"claim_id": "cl1"}],
        evidence_records=[],
        markdown="# 报告\n\n正文",
    )

    assert result["passed"] is False
    assert result["details"][0]["issues"] == [
        "empty_chart_data",
        "title_not_referenced_in_report",
        "no_supporting_claim_data",
    ]
