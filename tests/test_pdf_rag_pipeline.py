import json

from src.agents.final_answer_agent import _sanitize_pdf_gap_language
from src.agents.section_dossier_builder import SectionDossierBuilder
from src.data.pdf_rag_pipeline import build_pdf_chunks, build_pdf_rag_artifacts, build_section_map, summarize_pdf_section


def test_pdf_rag_v2_artifacts_are_written_without_cached_pdf(tmp_path):
    payload = build_pdf_rag_artifacts(
        pdf_artifacts={"pdf_manifest": []},
        output_dir=tmp_path,
        symbol="600519.SS",
        period="FY2025",
    )

    assert (tmp_path / "pdf_section_chunks.jsonl").exists()
    assert (tmp_path / "pdf_table_chunks.jsonl").exists()
    assert json.loads((tmp_path / "pdf_extraction_audit.json").read_text(encoding="utf-8"))["failure_reason"] == "no_cached_pdf"
    assert json.loads((tmp_path / "pdf_section_summaries.json").read_text(encoding="utf-8")) == []
    assert payload["pdf_extraction_audit"]["page_count"] == 0


def test_a_share_heading_discovery_scans_beyond_first_8_pages():
    pages = {idx: f"普通正文第 {idx} 页" for idx in range(1, 13)}
    pages[10] = "第三节 管理层讨论与分析\n公司围绕主营业务、渠道与未来发展展开讨论。"
    pages[11] = "第四节 公司治理\n董事会、监事会和高级管理人员情况。"
    pages[12] = "第十节 财务报告\n合并资产负债表 合并利润表 合并现金流量表。"

    section_map = build_section_map(pages, report_type="a_share")

    assert section_map["management_discussion"]["pages"][0] == 10
    assert section_map["ownership_governance"]["pages"][0] == 11
    assert section_map["financial_statements"]["pages"][0] == 12


def test_noise_filter_does_not_globally_ban_directors_inside_governance_section():
    chunks, _ = build_pdf_chunks(
        text_by_page={
            4: "第四节 公司治理\n董事会由多名董事组成，高级管理人员履行经营管理职责，监事会负责监督。"
        },
        section_map={"ownership_governance": {"title": "公司治理", "pages": (4, 4)}},
        symbol="600519.SS",
        period="FY2025",
    )

    usable = [chunk for chunk in chunks if chunk["usable_for_generation"]]
    assert usable
    assert usable[0]["section_type"] == "ownership_governance"
    assert "董事会" in usable[0]["text_clean"]


def test_business_summary_gap_mentions_specific_missing_business_fields():
    summary = summarize_pdf_section("business_overview", [], symbol="600519.SS", period="FY2025")

    assert summary["usable_for_generation"] is False
    assert "主营业务" in summary["summary_zh"]
    assert "产品结构" in summary["summary_zh"]


def test_section_dossier_uses_pdf_summary_when_available():
    dossiers = SectionDossierBuilder().build(
        state={
            "symbol": "600519.SS",
            "period": "FY2025",
            "pdf_section_summaries": [
                {
                    "section_type": "business_overview",
                    "summary_zh": "贵州茅台主营贵州茅台酒系列产品，渠道以直销和批发代理为主。",
                    "evidence_id": "pdf_summary_business",
                    "usable_for_generation": True,
                    "evidence_quality": "strong",
                }
            ],
        },
        analysis_artifacts={"company_profile": {"company_name": "贵州茅台"}},
    )

    business = dossiers["business_overview"]
    assert business["min_content_level"] == "full"
    assert business["supporting_evidence_ids"] == ["pdf_summary_business"]
    assert "贵州茅台酒" in business["suggested_paragraphs"][0]


def test_final_report_no_duplicate_symbol_in_business_overview():
    text = _sanitize_pdf_gap_language("600519.SS（600519.SS）资料缺口：本节暂无充足的可验证证据支持详细分析。。")

    assert "600519.SS（600519.SS）" not in text
    assert "。。" not in text
    assert "本节尚未获得可直接支撑分析的官方章节摘要" in text
