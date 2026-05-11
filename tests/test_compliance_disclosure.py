from src.report.compliance_disclosure import append_compliance_disclosures, append_compliance_disclosures_to_html


def test_append_compliance_disclosures_once():
    markdown = append_compliance_disclosures(
        "# 报告\n\n正文",
        citations=[{"source_authority": "official"}, {"source_authority": "market_data"}],
    )
    markdown = append_compliance_disclosures(markdown, citations=[{"source_authority": "official"}])

    assert markdown.count("## 合规披露与风险提示") == 1
    assert "投资评级" in markdown
    assert "official 1 条" in markdown


def test_append_compliance_disclosures_to_html_inside_main():
    html = append_compliance_disclosures_to_html(
        "<html><body><main><p>正文</p></main></body></html>",
        citations=[{"source_authority": "official"}],
    )

    assert "compliance-disclosure" in html
    assert html.index("compliance-disclosure") < html.index("</main>")
