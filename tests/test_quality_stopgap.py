import json

from src.data.pdf_rag_pipeline import summarize_pdf_section
from src.evaluation.report_quality import evaluate_report_quality


def test_mojibake_pdf_summary_is_not_usable_for_generation():
    summary = summarize_pdf_section(
        "business_overview",
        [
            {
                "chunk_id": "bad_mojibake",
                "text_clean": "璐靛窞鑼呭彴 2025 鈥滀簲澶ф牳蹇冪珵浜夊姏鈥?",
                "usable_for_generation": True,
                "is_noise": False,
            }
        ],
        symbol="600519.SS",
        period="FY2025",
    )

    assert summary["usable_for_generation"] is False
    assert summary["gap_reason"] in {"noise_only", "mojibake"}


def test_business_summary_is_compacted_before_generation():
    long_text = "公司主营业务包括茅台酒、系列酒、直销、i茅台和批发代理渠道。" * 20
    summary = summarize_pdf_section(
        "business_overview",
        [{"chunk_id": "biz", "text_clean": long_text, "usable_for_generation": True, "is_noise": False}],
        symbol="600519.SS",
        period="FY2025",
    )

    assert summary["usable_for_generation"] is True
    assert len(summary["summary_zh"]) <= 700


def test_company_info_pdf_chunk_not_usable_as_business_overview():
    summary = summarize_pdf_section(
        "business_overview",
        [
            {
                "chunk_id": "company_info",
                "text_clean": "第一节 释义 第二节 公司简介和主要财务指标 法定代表人 联系人和联系方式。",
                "usable_for_generation": True,
                "is_noise": False,
            }
        ],
        symbol="600519.SS",
        period="FY2025",
    )

    assert summary["usable_for_generation"] is False


def test_business_summary_strips_pdf_report_boilerplate():
    summary = summarize_pdf_section(
        "business_overview",
        [
            {
                "chunk_id": "business",
                "text_clean": "贵州茅台酒股份有限公司 2025 年年度报告 第三节 主营业务 公司主营业务包括茅台酒和系列酒，销售渠道覆盖直销、i茅台与批发代理。公司围绕产品结构、销售渠道和品牌建设推进经营模式优化，核心业务仍聚焦高端白酒和系列酒。",
                "usable_for_generation": True,
                "is_noise": False,
            }
        ],
        symbol="600519.SS",
        period="FY2025",
    )

    assert summary["usable_for_generation"] is True
    assert "年度报告" not in summary["summary_zh"]
    assert "第三节" not in summary["summary_zh"]
    assert "主营业务" in summary["summary_zh"]


def test_quality_blocks_usable_mojibake_pdf_summary(tmp_path):
    run_dir = _write_minimal_run(tmp_path, "<html><body><h1>600519.SS</h1><p>business report</p></body></html>")
    outputs = run_dir / "company" / "outputs"
    (outputs / "pdf_extraction_audit.json").write_text(json.dumps({"page_count": 120, "extracted_page_count": 40}), encoding="utf-8")
    (outputs / "pdf_section_summaries.json").write_text(
        json.dumps(
            [
                {
                    "section_type": "business_overview",
                    "summary_zh": "璐靛窞鑼呭彴 2025 鈥滀簲澶ф牳蹇冪珵浜夊姏鈥?",
                    "usable_for_generation": True,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = evaluate_report_quality(run_dir)

    assert any(issue["category"] == "pdf_rag" and "mojibake" in issue["message"] for issue in report["issues"])


def test_quality_does_not_treat_cny_as_symbol_pollution(tmp_path):
    run_dir = _write_minimal_run(tmp_path, "<html><body><h1>Kweichow Moutai (600519.SS)</h1><p>Revenue in CNY.</p></body></html>", symbol="600519.SS")

    report = evaluate_report_quality(run_dir)

    pollution_messages = [
        issue["message"]
        for issue in report["issues"]
        if issue["category"] == "cross_report_symbol_pollution"
    ]
    assert all("CNY" not in message for message in pollution_messages)


def _write_minimal_run(tmp_path, report_html: str, symbol: str = "600519.SS"):
    run_dir = tmp_path / "sample_run"
    outputs = run_dir / "company" / "outputs"
    reports = run_dir / "company" / "reports"
    outputs.mkdir(parents=True)
    reports.mkdir(parents=True)
    files = {
        "run_summary.json": {"symbol": symbol, "period": "FY2025", "verification_passed": True},
        "claims.json": [],
        "evidence.json": [],
        "citations.json": [],
        "tables.json": [],
        "financial_metrics.json": {},
        "charts.json": [],
        "verification_report.json": {"passed": True},
    }
    for name, payload in files.items():
        (outputs / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    (reports / "report.md").write_text("# Report\n\n## 业务概览\nRevenue in CNY.\n\n## 风险评估\nRisk note.\n\n## 投资结论\nNeutral.", encoding="utf-8")
    (reports / "report.html").write_text(report_html, encoding="utf-8")
    return run_dir
