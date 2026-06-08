"""Tests for chart_generator: user-readable labels and category separation."""

from src.report.chart_generator import (
    METRIC_LABEL_MAP,
    _categorize_metric_points,
    _confidence_points_from_claims,
    _metric_points_from_claims,
    generate_report_charts,
)


def test_metric_labels_are_user_readable():
    """Metric labels use Chinese names, not internal claim_id:key."""
    claims = [
        {
            "claim_id": "cl_0001",
            "claim": "收入增长",
            "numeric_values": {"revenue_billion": 35.4, "net_income_billion": 9.7},
        },
        {
            "claim_id": "cl_0002",
            "claim": "盈利能力",
            "numeric_values": {"gross_margin_pct": 52.1, "roe_pct": 15.0},
        },
    ]
    points = _metric_points_from_claims(claims)
    labels = [p[0] for p in points]

    # No internal IDs in labels
    assert not any("cl_" in label for label in labels), f"Found cl_ prefix in labels: {labels}"
    assert not any(":" in label for label in labels), f"Found colon in labels: {labels}"

    # Chinese readable labels present
    assert "收入" in labels
    assert "净利润" in labels
    assert "毛利率" in labels
    assert "ROE" in labels


def test_metric_label_map_has_common_keys():
    """METRIC_LABEL_MAP covers essential financial metric keys."""
    essential = [
        "revenue_billion", "net_income_billion", "total_assets_billion",
        "gross_margin_pct", "net_margin_pct", "roe_pct",
        "operating_cash_flow_billion", "free_cash_flow_billion",
    ]
    for key in essential:
        assert key in METRIC_LABEL_MAP, f"Missing essential key: {key}"
        assert METRIC_LABEL_MAP[key], f"Empty label for key: {key}"


def test_confidence_labels_are_readable():
    """Confidence labels use claim title/text, not claim_id."""
    claims = [
        {"claim_id": "cl_0001", "title": "收入增长判断", "claim": "revenue growth", "confidence": 0.9},
        {"claim_id": "cl_0002", "claim": "利润率判断", "confidence": 0.85},
    ]
    points = _confidence_points_from_claims(claims)
    labels = [p[0] for p in points]

    assert not any("cl_" in label for label in labels), f"Found cl_ prefix: {labels}"
    assert "收入增长判断" in labels
    assert "利润率判断" in labels


def test_categorize_separates_scale_and_ratios():
    """_categorize_metric_points splits metrics by category."""
    claims = [
        {
            "claim_id": "cl_1",
            "numeric_values": {
                "revenue_billion": 35.4,
                "gross_margin_pct": 52.1,
                "operating_cash_flow_billion": 12.3,
                "pe_ratio": 30.0,
            },
        },
    ]
    categories = _categorize_metric_points(claims)

    assert "financial_scale" in categories
    assert "profitability" in categories
    assert "cash_flow" in categories
    assert "valuation" in categories

    scale_labels = [p[0] for p in categories["financial_scale"]]
    assert "收入" in scale_labels

    profit_labels = [p[0] for p in categories["profitability"]]
    assert "毛利率" in profit_labels

    cf_labels = [p[0] for p in categories["cash_flow"]]
    assert "经营现金流" in cf_labels


def test_generate_report_charts_no_internal_ids(tmp_path):
    """Generated chart payloads should not contain internal IDs in labels."""
    claims = [
        {
            "claim_id": "cl_0001",
            "claim": "收入增长",
            "confidence": 0.9,
            "numeric_values": {"revenue_billion": 35.4},
            "evidence_ids": ["ev_001"],
        },
    ]
    charts = generate_report_charts(claims=claims, evidence_records=[], output_dir=str(tmp_path))

    for chart in charts:
        chart_js = chart.get("chart_js", {})
        if isinstance(chart_js, dict):
            for label in chart_js.get("labels", []):
                assert "cl_" not in label, f"Found cl_ in label: {label}"
                assert ":" not in label, f"Found colon in label: {label}"


def test_generate_report_charts_excludes_diagnostic_confidence_by_default(tmp_path):
    claims = [
        {
            "claim_id": "cl_0001",
            "claim": "收入增长",
            "confidence": 0.9,
            "numeric_values": {"revenue_billion": 35.4, "net_income_billion": 9.7},
            "evidence_ids": ["ev_001"],
        },
        {"claim_id": "cl_0002", "claim": "风险判断", "confidence": 0.7, "evidence_ids": ["ev_002"]},
    ]

    charts = generate_report_charts(
        claims=claims,
        evidence_records=[{"evidence_id": "ev_001", "source_type": "eastmoney_financials"}],
        output_dir=str(tmp_path),
    )

    chart_ids = {chart.get("chart_id") for chart in charts}
    assert "financial_scale_bar" in chart_ids
    assert "财务规模" not in chart_ids
    assert "claim_confidence_bar" not in chart_ids
    assert "evidence_source_mix" not in chart_ids


def test_generate_report_charts_uses_plain_metric_keys_and_peer_artifacts(tmp_path):
    claims = [
        {
            "claim_id": "cl_0001",
            "numeric_values": {
                "revenue": 10000000000,
                "net_income": 2000000000,
                "operating_cash_flow": 3000000000,
                "investing_cash_flow": -1000000000,
            },
            "evidence_ids": ["ev_income", "ev_cash"],
        }
    ]
    artifacts = {
        "peer_analysis": {
            "rows": [
                {"symbol": "000001.SS", "is_target": True, "net_margin_pct": 20},
                {"symbol": "000002.SS", "company_name": "Peer A", "net_margin_pct": 12},
            ]
        }
    }

    charts = generate_report_charts(
        claims=claims,
        evidence_records=[],
        output_dir=str(tmp_path),
        analysis_artifacts=artifacts,
    )

    chart_ids = {chart.get("chart_id") for chart in charts}
    assert "financial_scale_bar" in chart_ids
    assert "cash_flow_bar" in chart_ids
    assert "peer_compare_bar" in chart_ids
