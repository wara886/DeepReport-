import json

from src.agents.final_answer_agent import _sanitize_pdf_gap_language
from src.agents.section_dossier_builder import SectionDossierBuilder
from src.data.pdf_rag_pipeline import (
    build_pdf_chunks,
    build_pdf_rag_artifacts,
    build_section_map,
    detect_report_market,
    identify_toc_pages,
    parse_printed_toc_pages,
    retrieve_pdf_section_chunks,
    resolve_embedding_model,
    summarize_pdf_section,
)
from src.retrieval.bm25_index import BM25Index
from src.retrieval.evidence_store import EvidenceRecord


def test_market_aware_embedding_routes():
    assert detect_report_market("600519.SS", "年度报告", "https://www.cninfo.com.cn/a.pdf", "") == "cn_a"
    assert detect_report_market("0700.HK", "Annual Report", "https://www.hkexnews.hk/a.pdf", "") == "hk"
    assert detect_report_market("GOOGL", "Form 10-K", "https://www.sec.gov/a.htm", "") == "us"
    assert resolve_embedding_model("cn_a")["embedding_model"] == "BAAI/bge-small-zh-v1.5"
    assert resolve_embedding_model("us")["embedding_model"] == "BAAI/bge-small-en-v1.5"
    assert resolve_embedding_model("hk", "管理层讨论與分析 Corporate Governance " * 20)["embedding_model"] == "BAAI/bge-m3"


def test_chinese_bm25_recalls_business_terms():
    records = [
        EvidenceRecord.from_dict({"sample_id": "noise", "evidence_id": "noise", "content": "第一节 释义 公司信息 法定代表人 联系人和联系方式"}),
        EvidenceRecord.from_dict({"sample_id": "business", "evidence_id": "business", "content": "公司主营业务包括茅台酒和系列酒，产品结构覆盖高端白酒，销售渠道包括直销和批发代理。"}),
    ]
    hits = BM25Index(records).search("主营业务 产品结构 销售渠道", topk=1)

    assert hits
    assert hits[0].record.evidence_id == "business"


def test_printed_toc_pages_are_detected_without_becoming_body_headings():
    pages = {
        1: "目 录\n公司治理 ........ 12\n财务报告 ........ 88\n风险提示 ........ 40",
        2: "公司治理 12 风险提示 40 财务报告 88",
        12: "第四节 公司治理\n董事会、监事会和高级管理人员情况。",
        40: "重大风险提示\n市场竞争和监管变化可能影响经营。",
        88: "第十节 财务报告\n合并资产负债表 合并利润表 合并现金流量表。",
    }

    toc_pages = identify_toc_pages(pages)
    parsed = parse_printed_toc_pages(pages, "cn_a")
    section_map = build_section_map(pages, report_market="cn_a")

    assert 1 in toc_pages
    assert any(item["section_type"] == "ownership_governance" for item in parsed)
    assert section_map["ownership_governance"]["pages"][0] == 12
    assert section_map["ownership_governance"]["anchor_source"] in {"printed_toc_verified", "body_heading"}


def test_hk_and_us_section_schema_heading_discovery():
    hk_pages = {
        5: "Corporate Governance Report\nThe board and committee structure are described here.",
        9: "Management Discussion and Analysis\nRevenue, margins and liquidity are reviewed.",
    }
    us_pages = {
        4: "Item 1. Business\nWe operate search, cloud, and hardware segments.",
        12: "Item 1A. Risk Factors\nWe face intense competition and regulatory risk.",
        24: "Item 7. Management's Discussion and Analysis\nLiquidity and capital allocation are discussed.",
    }

    hk_map = build_section_map(hk_pages, report_market="hk")
    us_map = build_section_map(us_pages, report_market="us")

    assert hk_map["ownership_governance"]["pages"][0] == 5
    assert hk_map["management_discussion"]["pages"][0] == 9
    assert us_map["business_overview"]["pages"][0] == 4
    assert us_map["risk_factors"]["pages"][0] == 12
    assert us_map["management_discussion"]["pages"][0] == 24


def test_retrieve_pdf_section_chunks_prefers_relevant_business_chunks():
    candidate_chunks = [
        {
            "chunk_id": "business_good",
            "symbol": "600519.SS",
            "period": "FY2025",
            "section_type": "business_overview",
            "section_title": "业务概览",
            "text_clean": "公司主营业务包括高端白酒产品、品牌渠道建设和系列酒运营。",
            "text": "公司主营业务包括高端白酒产品、品牌渠道建设和系列酒运营。",
            "pages": [12],
            "page": 12,
            "source_url": "",
            "source_title": "",
            "anchor_source": "body_heading",
            "usable_for_generation": True,
            "is_noise": False,
            "quality_flags": [],
        },
        {
            "chunk_id": "business_bad",
            "symbol": "600519.SS",
            "period": "FY2025",
            "section_type": "business_overview",
            "section_title": "业务概览",
            "text_clean": "财务费用变动原因说明主要来自利息收入变动和汇率影响。",
            "text": "财务费用变动原因说明主要来自利息收入变动和汇率影响。",
            "pages": [13],
            "page": 13,
            "source_url": "",
            "source_title": "",
            "anchor_source": "body_heading",
            "usable_for_generation": True,
            "is_noise": False,
            "quality_flags": [],
        },
    ]

    top_chunks = retrieve_pdf_section_chunks("business_overview", candidate_chunks, "cn_a", top_k=1)

    assert top_chunks
    assert top_chunks[0]["chunk_id"] == "business_good"


def test_retrieve_pdf_section_chunks_skips_glossary_like_business_chunks():
    candidate_chunks = [
        {
            "chunk_id": "glossary_like",
            "symbol": "600519.SS",
            "period": "FY2025",
            "section_type": "business_overview",
            "section_title": "公司信息",
            "text_clean": "第一节 释义 公司信息 主要财务指标 法定代表人 联系人和联系方式。",
            "text": "第一节 释义 公司信息 主要财务指标 法定代表人 联系人和联系方式。",
            "pages": [3],
            "page": 3,
            "source_url": "",
            "source_title": "",
            "anchor_source": "body_heading",
            "usable_for_generation": True,
            "is_noise": False,
            "quality_flags": [],
        },
        {
            "chunk_id": "business_real",
            "symbol": "600519.SS",
            "period": "FY2025",
            "section_type": "business_overview",
            "section_title": "主营业务",
            "text_clean": "公司主营业务包括茅台酒和系列酒，销售渠道覆盖直销、i茅台与批发代理。",
            "text": "公司主营业务包括茅台酒和系列酒，销售渠道覆盖直销、i茅台与批发代理。",
            "pages": [18],
            "page": 18,
            "source_url": "",
            "source_title": "",
            "anchor_source": "body_heading",
            "usable_for_generation": True,
            "is_noise": False,
            "quality_flags": [],
        },
    ]

    top_chunks = retrieve_pdf_section_chunks("business_overview", candidate_chunks, "cn_a", top_k=2)

    assert top_chunks
    assert top_chunks[0]["chunk_id"] == "business_real"
    assert all(item["chunk_id"] != "glossary_like" for item in top_chunks)


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
