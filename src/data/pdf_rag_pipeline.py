"""Generalized PDF RAG v2 for annual-report section extraction."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

from src.data.content_governance import strip_pdf_boilerplate
from src.report.fact_extractors.pdf_encoding import auto_repair_mojibake
from src.retrieval.bm25_index import BM25Index
from src.retrieval.chroma_index import ChromaIndex
from src.retrieval.evidence_store import EvidenceRecord
from src.utils.config import load_config


SECTION_SCHEMA_VERSION = "pdf_rag_v2.1"

GENERIC_NOISE_PATTERNS = [
    (r"^\s*$", "empty"),
    (r"目录|目\s*录|table\s+of\s+contents", "toc_pointer"),
    (r"重要提示|声明|免责|disclaimer", "important_notice"),
    (r"适用\s*[√✔■☑].*不适用|不适用\s*[√✔■☑].*适用", "checkbox_boilerplate"),
    (r"审计报告|独立审计师|independent auditor", "audit_boilerplate"),
]

PAGE_HEADER_PATTERNS = [
    re.compile(r"^\s*\d+\s*/\s*\d+\s*$"),
    re.compile(r"^\s*page\s+\d+\s+of\s+\d+\s*$", re.I),
    re.compile(r"^\s*第\s*\d+\s*页\s*共\s*\d+\s*页\s*$"),
]

TABLE_HINT_PATTERNS = [
    re.compile(r"(资产负债表|利润表|现金流量表|balance sheet|income statement|cash flow statement)", re.I),
    re.compile(r"(收入|利润|资产|负债|现金|revenue|income|assets|liabilities|cash)", re.I),
]

# 短文档（≤20 页，如季度报告）的表格检测阈值更严格
SHORT_DOC_TABLE_DIGIT_THRESHOLD = 8   # 短文档要求 ≥8 个数字才判为表格
LONG_DOC_TABLE_DIGIT_THRESHOLD = 2    # 年报要求 ≥2 个数字

# RRF score 值域 ~0.01-0.02（基于排名倒数），不适合做绝对阈值
# section 过滤通过 page-range 约束实现，见 _retrieve_pdf_section_chunks_with_meta

CHINESE_SHORT_LINE_RE = re.compile(r"[\u4e00-\u9fff]")
TICKER_LIKE_RE = re.compile(r"\b(?:\d{4}\.HK|\d{6}\.(?:SS|SZ)|[A-Z]{1,6})\b")

MOJIBAKE_PATTERNS = [
    r"\uFFFD",
    r"璐靛|璇佹嵁|缁撹|锟",
    r"鈥|鈭|鈻|鈹",
    r"璐靛|璇佹|缁撹|鎽樿|鐩",
    r"鍏|涓氬|绠＄|锛|銆|€",
    r"[ÃÂ]",
]

BUSINESS_POSITIVE_TERMS = [
    "主营业务",
    "经营模式",
    "产品结构",
    "销售渠道",
    "茅台酒",
    "系列酒",
    "直销",
    "i茅台",
    "批发代理",
    "business model",
    "products",
    "segments",
    "sales channels",
]

BUSINESS_NEGATIVE_TERMS = [
    "释义",
    "公司信息",
    "联系人和联系方式",
    "主要财务指标",
    "法定代表人",
    "财务费用变动原因说明",
    "现金流量净额变动原因说明",
    "company information",
    "contact information",
    "principal financial data",
]


SECTION_SCHEMAS: dict[str, dict[str, dict[str, Any]]] = {
    "cn_a": {
        "business_overview": {
            "canonical_title": "业务概览",
            "heading_patterns": [r"公司简介", r"主营业务", r"业务概览", r"经营范围", r"主要产品"],
            "toc_patterns": [r"公司简介", r"主营业务", r"业务概览"],
            "query_terms": ["主营业务 产品 渠道 品牌 分部 业务结构", "业务概览 核心产品 市场定位"],
            "negative_patterns": [r"财务费用变动原因说明", r"现金流量净额变动原因说明", r"会计政策"],
        },
        "management_discussion": {
            "canonical_title": "管理层讨论与分析",
            "heading_patterns": [r"管理层讨论", r"经营情况讨论与分析", r"经营情况分析", r"未来发展"],
            "toc_patterns": [r"管理层讨论", r"经营情况讨论与分析"],
            "query_terms": ["管理层讨论 分析 收入 利润 成本 经营 现金流 战略", "未来发展 经营计划 业务策略"],
            "negative_patterns": [r"重要提示", r"目录"],
        },
        "ownership_governance": {
            "canonical_title": "公司治理",
            "heading_patterns": [r"公司治理", r"董事会", r"监事会", r"高级管理人员"],
            "toc_patterns": [r"公司治理", r"董事会", r"监事会"],
            "query_terms": ["公司治理 董事会 监事会 高级管理人员 内控 独立董事", "治理结构 董监高"],
            "negative_patterns": [r"重要提示", r"审计报告"],
        },
        "shareholder_structure": {
            "canonical_title": "股份变动及股东情况",
            "heading_patterns": [r"股份变动", r"股东情况", r"前十名股东", r"控股股东", r"实际控制人"],
            "toc_patterns": [r"股份变动", r"股东情况", r"控股股东"],
            "query_terms": ["股份变动 股东情况 前十名股东 控股股东 实际控制人", "股东结构 持股比例"],
            "negative_patterns": [r"股票简称", r"证券代码"],
        },
        "risk_factors": {
            "canonical_title": "风险提示",
            "heading_patterns": [r"风险提示", r"风险因素", r"可能面对的风险", r"未来发展风险"],
            "toc_patterns": [r"风险提示", r"风险因素"],
            "query_terms": ["风险因素 行业竞争 原材料 波动 监管 风险", "未来发展 风险提示"],
            "negative_patterns": [r"审计报告", r"财务费用变动原因说明"],
        },
        "financial_statements": {
            "canonical_title": "财务报告",
            "heading_patterns": [r"财务报告", r"审计报告", r"资产负债表", r"利润表", r"现金流量表"],
            "toc_patterns": [r"财务报告", r"审计报告"],
            "query_terms": ["财务报告 资产负债表 利润表 现金流量表", "合并报表 会计报表"],
            "negative_patterns": [],
        },
    },
    "hk": {
        "business_overview": {
            "canonical_title": "Business Overview",
            "heading_patterns": [r"business overview", r"business review", r"company profile", r"principal activities"],
            "toc_patterns": [r"business overview", r"principal activities", r"business review"],
            "query_terms": ["principal activities segments products business overview", "business review operations"],
            "negative_patterns": [r"finance costs", r"cash flows from operating activities"],
        },
        "management_discussion": {
            "canonical_title": "MD&A",
            "heading_patterns": [r"management discussion", r"management discussion and analysis", r"financial review", r"operating review"],
            "toc_patterns": [r"management discussion", r"financial review", r"operating review"],
            "query_terms": ["management discussion analysis revenue margins liquidity strategy", "financial review operating review"],
            "negative_patterns": [r"notes to the financial statements"],
        },
        "ownership_governance": {
            "canonical_title": "Corporate Governance",
            "heading_patterns": [r"corporate governance", r"governance report", r"board of directors", r"committee"],
            "toc_patterns": [r"corporate governance", r"governance report"],
            "query_terms": ["corporate governance board committee directors independence", "governance report"],
            "negative_patterns": [r"important notice", r"auditor"],
        },
        "shareholder_structure": {
            "canonical_title": "Substantial Shareholders",
            "heading_patterns": [r"substantial shareholders", r"interests of directors", r"share capital", r"share option"],
            "toc_patterns": [r"substantial shareholders", r"share capital", r"interests of directors"],
            "query_terms": ["substantial shareholders share capital controlling shareholder", "interests of directors shareholders"],
            "negative_patterns": [r"stock code"],
        },
        "risk_factors": {
            "canonical_title": "Risk Factors",
            "heading_patterns": [r"risk factors", r"principal risks", r"risk management"],
            "toc_patterns": [r"risk factors", r"principal risks", r"risk management"],
            "query_terms": ["principal risks competition regulation macro liquidity", "risk management risk factors"],
            "negative_patterns": [r"auditor"],
        },
        "financial_statements": {
            "canonical_title": "Financial Statements",
            "heading_patterns": [r"financial statements", r"consolidated statement", r"independent auditor"],
            "toc_patterns": [r"financial statements", r"independent auditor"],
            "query_terms": ["consolidated statement financial statements balance sheet cash flow", "financial statements"],
            "negative_patterns": [],
        },
    },
    "us": {
        "business_overview": {
            "canonical_title": "Item 1. Business",
            "heading_patterns": [r"item\s*1\.?\s*business", r"business"],
            "toc_patterns": [r"item\s*1\.?\s*business"],
            "query_terms": ["item 1 business segments products customers strategy", "business overview segment revenue"],
            "negative_patterns": [r"finance costs", r"cash flows from operating activities"],
        },
        "management_discussion": {
            "canonical_title": "Item 7. MD&A",
            "heading_patterns": [r"item\s*7\.?\s*management", r"management'?s discussion", r"mda"],
            "toc_patterns": [r"item\s*7\.?\s*management"],
            "query_terms": ["item 7 management discussion analysis revenue margins liquidity capital", "MD&A strategy liquidity"],
            "negative_patterns": [r"item 8"],
        },
        "ownership_governance": {
            "canonical_title": "Item 10 / 12 Governance",
            "heading_patterns": [r"item\s*10\.?\s*directors", r"item\s*12\.?\s*security ownership", r"directors and executive officers"],
            "toc_patterns": [r"item\s*10", r"item\s*12"],
            "query_terms": ["directors executive officers board governance security ownership", "item 10 item 12 governance"],
            "negative_patterns": [r"proxy statement incorporation"],
        },
        "shareholder_structure": {
            "canonical_title": "Item 12. Security Ownership",
            "heading_patterns": [r"item\s*12\.?\s*security ownership", r"security ownership"],
            "toc_patterns": [r"item\s*12\.?\s*security ownership"],
            "query_terms": ["security ownership beneficial owners common stock holders", "shareholder ownership item 12"],
            "negative_patterns": [],
        },
        "risk_factors": {
            "canonical_title": "Item 1A. Risk Factors",
            "heading_patterns": [r"item\s*1a\.?\s*risk factors", r"risk factors"],
            "toc_patterns": [r"item\s*1a\.?\s*risk factors"],
            "query_terms": ["item 1a risk factors competition regulation demand supply", "risk factors principal risks"],
            "negative_patterns": [r"item 7"],
        },
        "financial_statements": {
            "canonical_title": "Item 8. Financial Statements",
            "heading_patterns": [r"item\s*8\.?\s*financial statements", r"financial statements"],
            "toc_patterns": [r"item\s*8\.?\s*financial statements"],
            "query_terms": ["item 8 financial statements balance sheet income statement cash flows", "financial statements"],
            "negative_patterns": [],
        },
    },
}

SECTION_SCHEMAS["generic"] = {
    key: dict(value)
    for key, value in SECTION_SCHEMAS["cn_a"].items()
}

CN_A_BUSINESS_OVERVIEW_EXTRA_NEGATIVES = [
    r"释义",
    r"公司信息",
    r"联系人和联系方式",
    r"主要财务指标",
    r"法定代表人",
    r"财务费用变动原因说明",
    r"现金流量净额变动原因说明",
    r"company information",
    r"contact information",
    r"principal financial data",
]
CN_A_BUSINESS_OVERVIEW_EXTRA_QUERIES = [
    "主营业务 经营模式 产品结构 销售渠道 茅台酒 系列酒 直销 i茅台 批发代理",
    "business model products segments sales channels",
]
for _market in ("cn_a", "generic"):
    _config = SECTION_SCHEMAS.get(_market, {}).get("business_overview", {})
    if isinstance(_config, dict):
        _config["negative_patterns"] = list(_config.get("negative_patterns", [])) + CN_A_BUSINESS_OVERVIEW_EXTRA_NEGATIVES
        _config["query_terms"] = list(_config.get("query_terms", [])) + CN_A_BUSINESS_OVERVIEW_EXTRA_QUERIES


def detect_report_market(symbol: str, source_title: str = "", pdf_url: str = "", text_sample: str = "") -> str:
    symbol_upper = str(symbol or "").strip().upper()
    title = f"{source_title} {pdf_url} {text_sample}".lower()
    if symbol_upper.endswith((".SS", ".SZ")):
        return "cn_a"
    if symbol_upper.endswith(".HK"):
        return "hk"
    if symbol_upper and "." not in symbol_upper:
        return "us"
    if "cninfo" in title or "年度报告" in title or "半年度报告" in title:
        return "cn_a"
    if "hkex" in title or "annual report" in title and "hong kong" in title:
        return "hk"
    if any(term in title for term in ["10-k", "form 10-k", "sec", "edgar"]):
        return "us"
    return "generic"


def resolve_embedding_model(report_market: str, text_sample: str = "", config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config if isinstance(config, dict) else _load_retrieval_config()
    router = {}
    if isinstance(config, dict):
        retrieval = config.get("retrieval", config)
        if isinstance(retrieval, dict):
            router = retrieval.get("embedding_router", {}) if isinstance(retrieval.get("embedding_router"), dict) else {}
    defaults = {
        "default": "BAAI/bge-small-en-v1.5",
        "us": "BAAI/bge-small-en-v1.5",
        "cn_a": "BAAI/bge-small-zh-v1.5",
        "hk": "BAAI/bge-small-zh-v1.5",
        "generic_multilingual": "BAAI/bge-m3",
    }
    merged = {**defaults, **router}
    market = str(report_market or "generic").lower()
    text = str(text_sample or "")
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    mixed = cjk >= 40 and latin >= 120
    if market == "hk" and mixed:
        model = str(merged.get("generic_multilingual") or "BAAI/bge-m3")
        reason = "hk_mixed_language"
    elif market in {"us", "cn_a", "hk"}:
        model = str(merged.get(market) or merged["default"])
        reason = f"{market}_route"
    else:
        model = str(merged.get("generic_multilingual") or merged["default"])
        reason = "generic_route"
    return {
        "report_market": market,
        "embedding_model": model,
        "embedding_backend": "sentence_transformers_or_hash_fallback",
        "route_reason": reason,
        "fallback_reason": "",
    }


def get_section_schema(report_market: str) -> dict[str, dict[str, Any]]:
    return SECTION_SCHEMAS.get(report_market, SECTION_SCHEMAS["generic"])


def identify_toc_pages(text_by_page: dict[int, str]) -> list[int]:
    toc_pages: list[int] = []
    for page_num, text in sorted(text_by_page.items()):
        lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
        if len(lines) < 3:
            continue
        score = 0
        if any(re.search(r"(目\s*录|目录|table\s+of\s+contents)", line, re.I) for line in lines[:10]):
            score += 3
        toc_like = 0
        for line in lines[:80]:
            if re.search(r"(\.{2,}|…{2,}|\s{2,})\s*\d+\s*$", line):
                toc_like += 1
        if toc_like >= 4:
            score += 3
        if toc_like >= 2 and any(re.search(r"(章|节|item\s+\d|business|risk|治理|股东|财务报告)", line, re.I) for line in lines[:60]):
            score += 2
        if score >= 4:
            toc_pages.append(page_num)
    return toc_pages


def parse_printed_toc_pages(text_by_page: dict[int, str], report_market: str) -> list[dict[str, Any]]:
    schema = get_section_schema(report_market)
    toc_pages = identify_toc_pages(text_by_page)
    entries: list[dict[str, Any]] = []
    for page_num in toc_pages:
        for raw in str(text_by_page.get(page_num) or "").splitlines():
            line = raw.strip()
            if not line or len(line) > 180:
                continue
            page_match = re.search(r"(\d+)\s*$", line)
            if not page_match:
                continue
            for section_type, config in schema.items():
                if _matches_patterns(line, config.get("toc_patterns", [])):
                    entries.append(
                        {
                            "toc_page": page_num,
                            "section_type": section_type,
                            "title": str(config.get("canonical_title") or section_type),
                            "matched_toc_line": line,
                            "target_page": int(page_match.group(1)),
                        }
                    )
                    break
    return entries


def build_section_map(
    text_by_page: dict[int, str],
    report_type: str = "a_share",
    toc_entries: list[list[Any]] | None = None,
    report_market: str | None = None,
) -> dict[str, dict[str, Any]]:
    market = report_market or _normalize_report_market(report_type)
    schema = get_section_schema(market)
    if not text_by_page:
        return {}

    toc_pages = set(identify_toc_pages(text_by_page))
    candidates: list[dict[str, Any]] = []

    for entry in toc_entries or []:
        if not isinstance(entry, (list, tuple)) or len(entry) < 3:
            continue
        title = str(entry[1] or "").strip()
        try:
            page = int(entry[2])
        except (TypeError, ValueError):
            continue
        for section_type, config in schema.items():
            if _matches_patterns(title, config.get("heading_patterns", [])) or _matches_patterns(title, config.get("toc_patterns", [])):
                candidates.append(
                    {
                        "page": page,
                        "section_type": section_type,
                        "title": str(config.get("canonical_title") or section_type),
                        "anchor_source": "bookmark",
                        "anchor_confidence": 1.0,
                        "matched_heading": title,
                        "matched_toc_line": "",
                    }
                )
                break

    # 书签页码校正：扫描全文验证每个 bookmark 标题实际出现的页面
    # CNINFO PDF 的书签经常指向目录页（第 2-4 页）而非正文位置，
    # 导致 section_map 的页范围完全错误。
    if candidates:
        candidates = _correct_bookmark_pages(
            candidates, text_by_page, schema, toc_pages,
        )

    for toc_entry in parse_printed_toc_pages(text_by_page, market):
        target_page = int(toc_entry["target_page"])
        verified_heading = _verify_heading_near_page(text_by_page, target_page, toc_entry["section_type"], schema, toc_pages)
        candidates.append(
            {
                "page": verified_heading["page"] if verified_heading else target_page,
                "section_type": str(toc_entry["section_type"]),
                "title": str(toc_entry["title"]),
                "anchor_source": "printed_toc_verified" if verified_heading else "printed_toc_unverified",
                "anchor_confidence": 0.92 if verified_heading else 0.68,
                "matched_heading": str(verified_heading["line"]) if verified_heading else "",
                "matched_toc_line": str(toc_entry["matched_toc_line"]),
            }
        )

    for page_num, text in sorted(text_by_page.items()):
        if page_num in toc_pages:
            continue
        lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
        for line in lines[:120]:
            # 跳过 TOC 格式行（"第十节 财务报告 ...... 53"）
            if re.search(r"[\.…]{3,}\s*\d+\s*$", line):
                continue
            if not _looks_like_heading(line):
                continue
            for section_type, config in schema.items():
                if _matches_patterns(line, config.get("heading_patterns", [])):
                    candidates.append(
                        {
                            "page": page_num,
                            "section_type": section_type,
                            "title": str(config.get("canonical_title") or section_type),
                            "anchor_source": "body_heading",
                            "anchor_confidence": 0.84,
                            "matched_heading": line,
                            "matched_toc_line": "",
                        }
                    )
                    break

    # pdf_section_detector 补充检测：对全文做标题匹配，补全 body_heading 可能漏过的节
    _supplement_with_text_detector(candidates, text_by_page, schema, market)

    # 短文档后备方案（≤20 页）：
    # 若标题匹配未找到足够 section，或 bookmark 页码过于集中在前 3 页
    # （CNINFO 季度报告 bookmark 常指向目录页），按典型季度报告页面分布分配
    max_page = max(text_by_page)
    bookmark_front_heavy = sum(1 for c in candidates if c.get("anchor_source") == "bookmark" and int(c.get("page", 999)) <= 3) >= 2
    if max_page <= 20 and (len(candidates) < 3 or bookmark_front_heavy):
        _fallback_quarterly_map(candidates, text_by_page, max_page)

    selected = _dedupe_section_candidates(candidates)
    selected.sort(key=lambda row: int(row["page"]))
    max_page = max(text_by_page)
    section_map: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(selected):
        start_page = int(row["page"])
        next_page = int(selected[index + 1]["page"]) if index + 1 < len(selected) else max_page + 1
        end_page = max(start_page, next_page - 1)
        section_map[str(row["section_type"])] = {
            "title": str(row["title"]),
            "pages": (start_page, end_page),
            "page_count": end_page - start_page + 1,
            "anchor_source": str(row["anchor_source"]),
            "anchor_confidence": float(row["anchor_confidence"]),
            "matched_heading": str(row["matched_heading"]),
            "matched_toc_line": str(row["matched_toc_line"]),
        }
    return section_map


def build_pdf_rag_artifacts(
    pdf_artifacts: dict[str, Any],
    output_dir: str | Path,
    symbol: str = "",
    period: str = "",
    max_pages_per_section: int = 20,
    report_type: str = "a_share",
) -> dict[str, Any]:
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    manifests = pdf_artifacts.get("pdf_manifest", []) if isinstance(pdf_artifacts, dict) else []
    all_text_chunks: list[dict[str, Any]] = []
    all_table_chunks: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []

    for row in manifests if isinstance(manifests, list) else []:
        if not isinstance(row, dict):
            continue
        local_path = Path(str(row.get("file_path") or ""))
        if not local_path.exists():
            continue
        payload = extract_pdf_rag_v2(
            local_pdf_path=local_path,
            pdf_url=str(row.get("source_url") or ""),
            source_title=str(row.get("title") or ""),
            source_evidence_id=str(row.get("evidence_id") or ""),
            symbol=symbol,
            period=period,
            max_pages_per_section=max_pages_per_section,
            report_type=report_type,
        )
        all_text_chunks.extend(payload["text_chunks"])
        all_table_chunks.extend(payload["table_chunks"])
        summaries.extend(payload["section_summaries"])
        audits.append(payload["audit"])

    audit = _merge_audits(audits, symbol=symbol, period=period)
    _write_jsonl(output_root / "pdf_section_chunks.jsonl", all_text_chunks)
    _write_jsonl(output_root / "pdf_table_chunks.jsonl", all_table_chunks)
    (output_root / "pdf_extraction_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_root / "pdf_section_summaries.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "pdf_section_chunks": all_text_chunks,
        "pdf_table_chunks": all_table_chunks,
        "pdf_section_summaries": summaries,
        "pdf_extraction_audit": audit,
        "report_market": audit.get("report_market", "generic"),
        "section_schema_version": SECTION_SCHEMA_VERSION,
        "section_map": audit.get("section_map", {}),
        "retrieval_meta": audit.get("retrieval_meta", {}),
        "fallbacks_used": audit.get("fallbacks_used", []),
    }


def extract_pdf_rag_v2(
    local_pdf_path: str | Path,
    pdf_url: str = "",
    source_title: str = "",
    source_evidence_id: str = "",
    symbol: str = "",
    period: str = "",
    max_pages_per_section: int = 20,
    report_type: str = "a_share",
) -> dict[str, Any]:
    try:
        import fitz
    except Exception as exc:
        audit = _empty_audit(pdf_url, local_pdf_path, symbol, period, f"pymupdf_unavailable: {exc}")
        return {"text_chunks": [], "table_chunks": [], "section_summaries": [], "audit": audit}

    text_by_page: dict[int, str] = {}
    toc_entries: list[list[Any]] = []
    try:
        doc = fitz.open(str(local_pdf_path))
        page_count = len(doc)
        try:
            toc_entries = doc.get_toc(simple=True) or []
        except Exception:
            toc_entries = []
        for page_index in range(page_count):
            raw = doc[page_index].get_text() or ""
            text_by_page[page_index + 1] = _clean_pdf_page_text(raw)
        doc.close()
    except Exception as exc:
        audit = _empty_audit(pdf_url, local_pdf_path, symbol, period, f"pdf_parse_failed: {exc}")
        return {"text_chunks": [], "table_chunks": [], "section_summaries": [], "audit": audit}

    report_market = detect_report_market(
        symbol=symbol,
        source_title=source_title,
        pdf_url=pdf_url,
        text_sample="\n".join(text_by_page.get(page, "")[:400] for page in sorted(text_by_page)[:3]),
    )
    text_sample = "\n".join(text_by_page.get(page, "")[:400] for page in sorted(text_by_page)[:3])
    retrieval_config = _load_retrieval_config()
    embedding_route = resolve_embedding_model(report_market, text_sample=text_sample, config=retrieval_config)
    section_map = build_section_map(text_by_page, report_type=report_type, toc_entries=toc_entries, report_market=report_market)
    limited_pages = _pages_for_sections(text_by_page, section_map, max_pages_per_section=max_pages_per_section)
    text_chunks, table_chunks = build_pdf_chunks(
        limited_pages,
        section_map,
        symbol=symbol,
        period=period,
        source_url=pdf_url,
        source_title=source_title,
        report_market=report_market,
    )
    for chunk in text_chunks:
        chunk["source_evidence_id"] = source_evidence_id
    for chunk in table_chunks:
        chunk["source_evidence_id"] = source_evidence_id

    retrieval_meta: dict[str, Any] = {}
    fallbacks_used: list[str] = []
    summaries: list[dict[str, Any]] = []
    for section_type in _target_section_types(section_map, report_market):
        candidate_chunks = [chunk for chunk in text_chunks if str(chunk.get("section_type")) == section_type]
        section_info = section_map.get(section_type, {})
        section_pages = section_info.get("pages", None)
        section_page_range = (int(section_pages[0]), int(section_pages[1])) if section_pages and len(section_pages) >= 2 else None
        top_chunks, meta = _retrieve_pdf_section_chunks_with_meta(
            section_type,
            candidate_chunks,
            report_market,
            top_k=6,
            embedding_model=str(embedding_route.get("embedding_model") or ""),
            retrieval_config=retrieval_config,
            section_page_range=section_page_range,
        )
        retrieval_meta[section_type] = meta
        fallbacks_used.extend(meta.get("fallbacks_used", []))
        summary = summarize_pdf_section(section_type, top_chunks, symbol=symbol, period=period)
        section_info = section_map.get(section_type, {})
        summary.update(
            {
                "evidence_id": f"pdf_summary_{symbol}_{period}_{section_type}".replace(".", "_").lower(),
                "source_url": pdf_url,
                "source_title": source_title,
                "source_evidence_id": source_evidence_id,
                "section_title": str(section_info.get("title") or section_type),
                "pages": list(section_info.get("pages", [])),
                "anchor_source": str(section_info.get("anchor_source") or meta.get("anchor_source") or ""),
                "report_market": report_market,
                "section_schema_version": SECTION_SCHEMA_VERSION,
            }
        )
        summaries.append(summary)

    business_fallback = _business_summary_from_mda(
        summaries=summaries,
        text_chunks=text_chunks,
        report_market=report_market,
        embedding_model=str(embedding_route.get("embedding_model") or ""),
        retrieval_config=retrieval_config,
        symbol=symbol,
        period=period,
        pdf_url=pdf_url,
        source_title=source_title,
        source_evidence_id=source_evidence_id,
    )
    if business_fallback:
        summaries = [
            business_fallback if str(item.get("section_type")) == "business_overview" else item
            for item in summaries
        ]
        retrieval_meta["business_overview_mda_fallback"] = business_fallback.get("retrieval_meta", {})
        fallbacks_used.append("business_overview_from_management_discussion")

    failure_reason = ""
    if not section_map:
        failure_reason = "section_not_found"
    elif not any(item.get("usable_for_generation") for item in summaries):
        failure_reason = "section_extracted_but_noise_only"

    audit = _build_audit(
        pdf_url=pdf_url,
        local_pdf_path=local_pdf_path,
        symbol=symbol,
        period=period,
        page_count=len(text_by_page),
        extracted_page_count=len(limited_pages),
        toc_found=bool(toc_entries) or bool(identify_toc_pages(text_by_page)),
        section_map=section_map,
        chunks=text_chunks,
        failure_reason=failure_reason,
        report_market=report_market,
        retrieval_meta=retrieval_meta,
        fallbacks_used=sorted(set(fallbacks_used)),
        embedding_route=embedding_route,
    )
    return {
        "text_chunks": text_chunks,
        "table_chunks": table_chunks,
        "section_summaries": summaries,
        "audit": audit,
        "pdf_section_chunks": text_chunks,
        "pdf_table_chunks": table_chunks,
        "pdf_section_summaries": summaries,
        "pdf_extraction_audit": audit,
        "report_market": report_market,
        "section_schema_version": SECTION_SCHEMA_VERSION,
        "section_map": audit.get("section_map", {}),
        "retrieval_meta": retrieval_meta,
        "fallbacks_used": sorted(set(fallbacks_used)),
    }


def retrieve_pdf_section_chunks(section_type: str, candidate_chunks: list[dict[str, Any]], report_market: str, top_k: int = 6) -> list[dict[str, Any]]:
    retrieval_config = _load_retrieval_config()
    embedding_route = resolve_embedding_model(report_market, text_sample=" ".join(str(chunk.get("text_clean") or chunk.get("text") or "")[:200] for chunk in candidate_chunks[:3]), config=retrieval_config)
    chunks, _ = _retrieve_pdf_section_chunks_with_meta(
        section_type,
        candidate_chunks,
        report_market,
        top_k=top_k,
        embedding_model=str(embedding_route.get("embedding_model") or ""),
        retrieval_config=retrieval_config,
    )
    return chunks


def summarize_pdf_section(
    section_type: str,
    chunks: list[dict[str, Any]],
    symbol: str = "",
    period: str = "",
) -> dict[str, Any]:
    usable = [
        chunk
        for chunk in chunks
        if isinstance(chunk, dict)
        and chunk.get("usable_for_generation")
        and not chunk.get("is_noise")
        and not _has_mojibake(str(chunk.get("text_clean") or chunk.get("text") or chunk.get("summary_zh") or ""))
    ]
    if section_type == "business_overview":
        usable = [
            chunk
            for chunk in usable
            if _is_business_overview_text(str(chunk.get("text_clean") or chunk.get("text") or ""))
        ]
    if chunks and not usable:
        return _gap_summary(section_type, "noise_only", symbol, period)
    if not usable:
        return _gap_summary(section_type, "missing", symbol, period)

    combined = " ".join(str(chunk.get("text_clean") or chunk.get("text") or "")[:520] for chunk in usable[:4]).strip()
    combined = re.sub(r"\s{2,}", " ", combined)[:2200]
    combined = _compact_pdf_summary(combined)
    # 兜底：若 combined 含 mojibake，尝试修复后再判是否可用
    if _has_mojibake(combined):
        repaired, stats = auto_repair_mojibake(combined)
        if stats.get("action") == "repaired" and len(str(repaired or "").strip()) > 50:
            combined = repaired
        else:
            return _gap_summary(section_type, "mojibake", symbol, period)
    # Language-agnostic content quality check.
    # Instead of blocking by CJK ratio (which discards genuine English content
    # from Chinese companies that publish English annual reports), check whether
    # the text is TOC/navigation boilerplate or disclaimer boilerplate —
    # those are useless regardless of language.
    if _is_toc_text(combined) or _is_boilerplate_text(combined):
        return _gap_summary(section_type, "noise_only", symbol, period)

    if section_type == "business_overview" and not _is_business_overview_text(combined):
        return _gap_summary(section_type, "noise_only", symbol, period)
    if section_type == "business_overview":
        quality = "strong" if len(combined) > 260 else "medium" if len(combined) > 50 else "weak"
    else:
        quality = "strong" if len(combined) > 500 else "medium" if len(combined) > 180 else "weak"
    return {
        "section_type": section_type,
        "summary_zh": combined,
        "source_chunk_ids": [str(chunk.get("chunk_id") or "") for chunk in usable[:4]],
        "retrieval_scores": [float(chunk.get("retrieval_score", 0.0) or 0.0) for chunk in usable[:4]],
        "anchor_source": str(usable[0].get("anchor_source") or "") if usable else "",
        "negative_filters_applied": _dedupe_text(
            reason
            for chunk in usable[:4]
            for reason in chunk.get("quality_flags", [])
            if str(reason).startswith("negative:")
        ),
        "evidence_quality": quality,
        "usable_for_generation": quality in {"strong", "medium"} and len(combined) <= 700,
        "is_noise": False,
    }


def _business_summary_from_mda(
    summaries: list[dict[str, Any]],
    text_chunks: list[dict[str, Any]],
    report_market: str,
    embedding_model: str,
    retrieval_config: dict[str, Any] | None,
    symbol: str,
    period: str,
    pdf_url: str,
    source_title: str,
    source_evidence_id: str,
) -> dict[str, Any] | None:
    current = next((item for item in summaries if str(item.get("section_type")) == "business_overview"), {})
    if current.get("usable_for_generation"):
        return None
    candidates = [
        chunk
        for chunk in text_chunks
        if str(chunk.get("section_type")) == "management_discussion"
        and chunk.get("usable_for_generation")
        and _looks_like_business_discussion(str(chunk.get("text_clean") or chunk.get("text") or ""))
    ]
    if not candidates:
        return None
    top_chunks, meta = _retrieve_pdf_section_chunks_with_meta(
        "business_overview",
        candidates,
        report_market,
        top_k=4,
        embedding_model=embedding_model,
        retrieval_config=retrieval_config,
    )
    if not top_chunks:
        return None
    summary = summarize_pdf_section("business_overview", top_chunks, symbol=symbol, period=period)
    if not summary.get("usable_for_generation"):
        return None
    summary.update(
        {
            "evidence_id": f"pdf_summary_{symbol}_{period}_business_overview".replace(".", "_").lower(),
            "source_url": pdf_url,
            "source_title": source_title,
            "source_evidence_id": source_evidence_id,
            "section_title": "管理层讨论与分析 / 从事业务情况",
            "pages": sorted({page for chunk in top_chunks for page in list(chunk.get("pages") or [])}),
            "anchor_source": "mda_business_fallback",
            "report_market": report_market,
            "section_schema_version": SECTION_SCHEMA_VERSION,
            "fallback_from_section": "management_discussion",
            "retrieval_meta": meta,
        }
    )
    return summary


def _looks_like_business_discussion(text: str) -> bool:
    positive_terms = [
        "主营业务",
        "从事的业务",
        "经营模式",
        "产品结构",
        "销售模式",
        "销售渠道",
        "茅台酒",
        "系列酒",
        "直销",
        "批发代理",
        "business model",
        "products",
        "segments",
        "sales channels",
    ]
    negative_terms = [
        "财务费用变动原因说明",
        "现金流量净额变动原因说明",
        "第一节 释义",
        "公司信息",
        "联系人和联系方式",
        "主要财务指标",
        "法定代表人",
    ]
    lowered = str(text or "").lower()
    if any(term.lower() in lowered for term in negative_terms):
        return False
    return any(term.lower() in lowered for term in positive_terms)


def build_pdf_chunks(
    text_by_page: dict[int, str],
    section_map: dict[str, dict[str, Any]],
    symbol: str = "",
    period: str = "",
    source_url: str = "",
    source_title: str = "",
    report_market: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    market = report_market or "generic"
    schema = get_section_schema(market)
    text_chunks: list[dict[str, Any]] = []
    table_chunks: list[dict[str, Any]] = []

    for section_type, info in section_map.items():
        start_page, end_page = info.get("pages", (0, 0))
        section_pages = {page: text for page, text in text_by_page.items() if int(start_page) <= int(page) <= int(end_page)}
        if not section_pages:
            continue
        blocks = _section_blocks(section_pages)
        chunk_index = 0
        for block in blocks:
            block_text = str(block["text"]).strip()
            if not block_text:
                continue
            if _looks_like_table(block_text, page_count=len(text_by_page)):
                table_chunk = _base_chunk(
                    chunk_id=f"pdf_tbl_{hashlib.sha1(f'{symbol}|{period}|{section_type}|{block_text}'.encode('utf-8')).hexdigest()[:12]}",
                    symbol=symbol,
                    period=period,
                    source_url=source_url,
                    source_title=source_title,
                    section_type=section_type,
                section_title=str(info.get("title") or section_type),
                block_type="table_row",
                text=block_text,
                pages=block["pages"],
                anchor_source=str(info.get("anchor_source") or ""),
                report_market=market,
                quality_flags=[],
                rejection_reason="",
                is_noise=False,
            )
                table_chunk["usable_for_generation"] = True
                table_chunks.append(table_chunk)
                continue

            flags, rejection_reason = _classify_chunk_noise(block_text, section_type, schema)
            is_noise = bool(rejection_reason)
            chunk = _base_chunk(
                chunk_id=f"pdf_{hashlib.sha1(f'{symbol}|{period}|{section_type}|{chunk_index}|{block_text}'.encode('utf-8')).hexdigest()[:12]}",
                symbol=symbol,
                period=period,
                source_url=source_url,
                source_title=source_title,
                section_type=section_type,
                section_title=str(info.get("title") or section_type),
                block_type="paragraph",
                text=block_text if not is_noise else "",
                pages=block["pages"],
                anchor_source=str(info.get("anchor_source") or ""),
                report_market=market,
                quality_flags=flags,
                rejection_reason=rejection_reason,
                is_noise=is_noise,
            )
            text_chunks.append(chunk)
            chunk_index += 1

    return text_chunks, table_chunks


def validate_peer_rows(peer_rows: list[dict[str, Any]], current_symbol: str) -> list[dict[str, Any]]:
    if not current_symbol:
        return [row for row in peer_rows if isinstance(row, dict)]
    current = str(current_symbol).strip().upper()
    filtered: list[dict[str, Any]] = []
    for row in peer_rows:
        if not isinstance(row, dict):
            continue
        row_symbol = str(row.get("symbol") or row.get("ticker") or "").strip().upper()
        row_name = str(row.get("company") or row.get("company_name") or row.get("公司") or "").strip().upper()
        if not row_symbol:
            filtered.append(row)
        elif row_symbol == current or current in row_name:
            filtered.append(row)
    return filtered


def _retrieve_pdf_section_chunks_with_meta(
    section_type: str,
    candidate_chunks: list[dict[str, Any]],
    report_market: str,
    top_k: int = 6,
    embedding_model: str = "",
    retrieval_config: dict[str, Any] | None = None,
    section_page_range: tuple[int, int] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    schema = get_section_schema(report_market)
    config = schema.get(section_type, {})
    queries = list(config.get("query_terms", [])) or [section_type]
    route = resolve_embedding_model(report_market, text_sample=" ".join(str(chunk.get("text_clean") or chunk.get("text") or "")[:200] for chunk in candidate_chunks[:3]), config=retrieval_config)
    model_name = embedding_model or str(route.get("embedding_model") or "")
    retrieval_meta: dict[str, Any] = {
        "queries": queries,
        "fallbacks_used": [],
        "rrf_k": 60,
        "bm25_weight": 0.55,
        "dense_weight": 0.45,
        "report_market": report_market,
        "embedding_model": model_name,
        "embedding_backend": "not_loaded",
        "dense_index_backend": "disabled",
        "rrf_used": True,
        "reranker_used": False,
        "bm25_hit_count": 0,
        "dense_hit_count": 0,
        "top_chunk_ids": [],
        "fallback_reason": "",
    }
    if not candidate_chunks:
        retrieval_meta["selected_count"] = 0
        return [], retrieval_meta

    records = [
        EvidenceRecord.from_dict(
            {
                "sample_id": str(chunk.get("chunk_id") or f"chunk_{idx}"),
                "evidence_id": str(chunk.get("chunk_id") or f"chunk_{idx}"),
                "source_type": "annual_report_pdf_chunk",
                "symbol": str(chunk.get("symbol") or ""),
                "period": str(chunk.get("period") or ""),
                "title": str(chunk.get("section_title") or section_type),
                "publish_time": "",
                "content": str(chunk.get("text_clean") or chunk.get("text") or ""),
                "source_url": str(chunk.get("source_url") or ""),
                "trust_level": "official",
            }
        )
        for idx, chunk in enumerate(candidate_chunks)
    ]
    chunk_by_id = {str(chunk.get("chunk_id")): dict(chunk) for chunk in candidate_chunks}

    bm25_scores: dict[str, float] = {}
    bm25_index = BM25Index(records)
    for query in queries:
        for hit in bm25_index.search(query, topk=min(30, len(records))):
            chunk_id = str(hit.record.evidence_id or hit.record.sample_id)
            bm25_scores[chunk_id] = max(float(hit.score), bm25_scores.get(chunk_id, 0.0))
    retrieval_meta["bm25_hit_count"] = len(bm25_scores)

    dense_scores: dict[str, float] = {}
    try:
        vector_index = ChromaIndex(model_name=model_name)
        vector_index.add_records(records)
        retrieval_meta["dense_index_backend"] = vector_index.backend
        retrieval_meta["embedding_backend"] = vector_index.embedding_backend
        if vector_index.embedding_backend == "hash_fallback":
            retrieval_meta["fallbacks_used"].append("embedding_hash_fallback")
        for query in queries:
            for hit in vector_index.search(query, topk=min(30, len(records))):
                chunk_id = str(hit.get("evidence_id") or hit.get("sample_id") or "")
                dense_scores[chunk_id] = max(float(hit.get("vector_score", 0.0) or 0.0), dense_scores.get(chunk_id, 0.0))
        retrieval_meta["dense_hit_count"] = len(dense_scores)
    except Exception:
        retrieval_meta["fallbacks_used"].append("dense_unavailable")
        retrieval_meta["fallback_reason"] = "dense_unavailable"

    rrf_scores = _rrf_fuse(bm25_scores, dense_scores, k=int(retrieval_meta["rrf_k"]))
    ranked = []
    for chunk_id, score in rrf_scores.items():
        chunk = dict(chunk_by_id.get(chunk_id, {}))
        if not chunk:
            continue
        penalty = 0.0
        text = str(chunk.get("text_clean") or chunk.get("text") or "")
        for pattern in config.get("negative_patterns", []):
            if re.search(str(pattern), text, re.I):
                penalty += 0.08
                chunk.setdefault("quality_flags", []).append(f"negative:{pattern}")
        chunk["retrieval_score"] = max(0.0, float(score) - penalty)
        ranked.append(chunk)
    ranked.sort(key=lambda row: float(row.get("retrieval_score", 0.0)), reverse=True)

    try:
        from src.training.infer_reranker import rerank_hits_with_meta

        reranked, rerank_meta = rerank_hits_with_meta(
            hits=[dict(item, score=float(item.get("retrieval_score", 0.0))) for item in ranked[:20]],
            query=" ".join(queries),
        )
        rerank_map = {
            str(item.get("evidence_id") or item.get("sample_id") or item.get("chunk_id") or ""): float(item.get("rerank_score", item.get("score", 0.0)) or 0.0)
            for item in reranked
        }
        for row in ranked:
            row_id = str(row.get("chunk_id") or "")
            if row_id in rerank_map:
                row["retrieval_score"] = max(float(row.get("retrieval_score", 0.0)), rerank_map[row_id])
                row["rerank_score"] = rerank_map[row_id]
        ranked.sort(key=lambda row: float(row.get("retrieval_score", 0.0)), reverse=True)
        retrieval_meta["reranker"] = rerank_meta.get("mode", "available")
        retrieval_meta["reranker_used"] = True
    except Exception:
        retrieval_meta["fallbacks_used"].append("reranker_unavailable")
        if not retrieval_meta.get("fallback_reason"):
            retrieval_meta["fallback_reason"] = "reranker_unavailable"

    # 按页范围过滤：物理上不属于此 section 页范围的 chunk 排除
    if section_page_range:
        pr_start, pr_end = section_page_range
        ranked = [
            c for c in ranked
            if any(pr_start <= int(p) <= pr_end for p in (c.get("pages") or [c.get("page") or 0]))
        ]

    selected: list[dict[str, Any]] = []
    per_page_count: dict[int, int] = {}
    for chunk in ranked:
        flags = chunk.get("quality_flags", []) if isinstance(chunk.get("quality_flags"), list) else []
        if section_type == "business_overview" and any(str(flag).startswith("negative:") for flag in flags):
            continue
        page = int((chunk.get("pages") or [chunk.get("page") or 0])[0] or 0)
        if per_page_count.get(page, 0) >= 2:
            continue
        selected.append(chunk)
        per_page_count[page] = per_page_count.get(page, 0) + 1
        if len(selected) >= top_k:
            break

    retrieval_meta["selected_count"] = len(selected)
    retrieval_meta["anchor_source"] = str(selected[0].get("anchor_source") or "") if selected else ""
    retrieval_meta["top_chunk_ids"] = [str(chunk.get("chunk_id") or "") for chunk in selected if str(chunk.get("chunk_id") or "")]
    return selected, retrieval_meta


def _rrf_fuse(bm25_scores: dict[str, float], dense_scores: dict[str, float], k: int = 60) -> dict[str, float]:
    def _rank_map(score_map: dict[str, float]) -> dict[str, int]:
        ranked = sorted(score_map.items(), key=lambda item: item[1], reverse=True)
        return {doc_id: index + 1 for index, (doc_id, _) in enumerate(ranked)}

    bm25_ranks = _rank_map(bm25_scores)
    dense_ranks = _rank_map(dense_scores)
    all_ids = set(bm25_ranks) | set(dense_ranks)
    fused: dict[str, float] = {}
    for doc_id in all_ids:
        score = 0.0
        if doc_id in bm25_ranks:
            score += 0.55 * (1.0 / (k + bm25_ranks[doc_id]))
        if doc_id in dense_ranks:
            score += 0.45 * (1.0 / (k + dense_ranks[doc_id]))
        fused[doc_id] = score
    return fused


def _section_blocks(section_pages: dict[int, str]) -> list[dict[str, Any]]:
    """三级智能切分：按文本长度 dispatch 不同策略。

    Stage 1: Section boundary — 由上游 section_map 保证
    Stage 2: 长度门控 — 短文本整段过，长文本按段落或滑动窗口
    Stage 3: 滑动窗口对齐句子末尾（非截断）
    """
    # 拼接当前 section 的所有页文本
    full_text = "\n".join(str(t) for t in section_pages.values())
    if not full_text.strip():
        return []

    length = len(full_text)

    # Stage 2: < 500 chars → 整段作为 1 个 block
    if length < 500:
        all_pages = sorted(section_pages.keys())
        return [{"text": full_text.strip(), "pages": all_pages}]

    # Stage 2: 500-2000 chars → 按段落边界切分
    if length <= 2000:
        blocks = []
        paragraphs = re.split(r"\n\s*\n", full_text.strip())
        for para in paragraphs:
            para = para.strip()
            if len(para) < 50:
                continue
            # 估算该段落在哪些页
            blocks.append({"text": para, "pages": sorted(section_pages.keys())})
        if not blocks:
            blocks.append({"text": full_text.strip(), "pages": sorted(section_pages.keys())})
        return blocks

    # Stage 2+3: > 2000 chars → 滑动窗口，对齐句子末尾
    page_blocks: list[dict[str, Any]] = []
    window_size = 1150
    overlap = 160
    for page_num, text in sorted(section_pages.items()):
        merged_lines = _merge_short_lines([line.strip() for line in str(text or "").splitlines()])
        current = ""
        current_pages: list[int] = []
        for line in merged_lines:
            if not line:
                continue
            # 当前行超过窗口 → 刷新 block，保留 overlap
            if len(current) + len(line) + 1 > window_size and current:
                page_blocks.append({"text": current.strip(), "pages": current_pages[:]})
                # 保留句尾内容作为 overlap，避免句子被截断
                carry = current[-overlap:] if len(current) > overlap + 20 else current
                current = carry
                current_pages = current_pages[-1:] if current_pages else []
            if current:
                current += " " + line
            else:
                current = line
            if page_num not in current_pages:
                current_pages.append(page_num)
        if current.strip():
            page_blocks.append({"text": current.strip(), "pages": current_pages[:] or [page_num]})
    return page_blocks


def _merge_short_lines(lines: list[str]) -> list[str]:
    merged: list[str] = []
    buffer = ""
    for raw in lines:
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            if buffer:
                merged.append(buffer.strip())
                buffer = ""
            continue
        if any(pattern.match(line) for pattern in PAGE_HEADER_PATTERNS):
            if buffer:
                merged.append(buffer.strip())
                buffer = ""
            continue
        if _looks_like_heading(line):
            if buffer:
                merged.append(buffer.strip())
                buffer = ""
            merged.append(line)
            continue
        short_cjk = bool(CHINESE_SHORT_LINE_RE.search(line)) and len(line) <= 28
        if short_cjk or len(line) <= 50:
            buffer = f"{buffer} {line}".strip()
        else:
            if buffer:
                merged.append(buffer.strip())
            buffer = line
    if buffer:
        merged.append(buffer.strip())
    return merged


def _base_chunk(
    *,
    chunk_id: str,
    symbol: str,
    period: str,
    source_url: str,
    source_title: str,
    section_type: str,
    section_title: str,
    block_type: str,
    text: str,
    pages: list[int],
    anchor_source: str,
    report_market: str = "",
    quality_flags: list[str],
    rejection_reason: str,
    is_noise: bool,
) -> dict[str, Any]:
    pages_sorted = sorted(set(int(page) for page in pages if page))
    return {
        "chunk_id": chunk_id,
        "evidence_id": chunk_id,
        "symbol": symbol,
        "period": period,
        "source_url": source_url,
        "source_title": source_title,
        "section_type": section_type,
        "section_title": section_title,
        "page": pages_sorted[0] if pages_sorted else 0,
        "pages": pages_sorted,
        "page_span": pages_sorted[:1] + pages_sorted[-1:] if pages_sorted else [],
        "anchor_source": anchor_source,
        "report_market": report_market,
        "block_type": block_type,
        # 编码修复：对 mojibake 文本 auto_repair_mojibake
        "text": text,
        "text_clean": "[{}] {}".format(section_title, _repair_text(text)) if section_title else _repair_text(text),
        "summary_zh": _compact_pdf_summary(_repair_text(text)) if not is_noise else "",
        "quality_flags": quality_flags,
        "rejection_reason": rejection_reason,
        "is_noise": is_noise,
        "usable_for_generation": not is_noise,
    }


def _classify_chunk_noise(text: str, section_type: str, schema: dict[str, dict[str, Any]]) -> tuple[list[str], str]:
    flags: list[str] = []
    lowered = str(text or "")
    if _has_mojibake(lowered):
        # 尝试修复编码，修复后再判断
        repaired, stats = auto_repair_mojibake(lowered)
        if stats.get("action") == "repaired" and len(str(repaired or "").strip()) >= 24:
            flags.append(f"mojibake_repaired:{stats.get('strategy', 'unknown')}")
        else:
            return ["mojibake"], "mojibake"
    for pattern, reason in GENERIC_NOISE_PATTERNS:
        if re.search(pattern, lowered, re.I):
            return [reason], reason
    if len(re.sub(r"\s+", "", lowered)) < 24:
        return ["too_short"], "too_short"
    section_config = schema.get(section_type, {})
    for pattern in section_config.get("negative_patterns", []):
        if re.search(str(pattern), lowered, re.I):
            flags.append(f"negative:{pattern}")
    if section_type == "business_overview" and not _is_business_overview_text(lowered):
        return flags + ["business_overview_negative_or_weak"], "business_overview_negative_or_weak"
    return flags, ""


def _has_mojibake(text: str) -> bool:
    value = str(text or "")
    if not value:
        return False
    return any(re.search(pattern, value) for pattern in MOJIBAKE_PATTERNS)


def _repair_text(text: str) -> str:
    """修复 mojibake 编码，若无乱码则返回原文。"""
    if not text:
        return text
    repaired, stats = auto_repair_mojibake(text)
    if stats.get("action") == "repaired":
        return repaired
    return text


def _supplement_with_text_detector(
    candidates: list[dict[str, Any]],
    text_by_page: dict[int, str],
    schema: dict[str, dict[str, Any]],
    market: str,
) -> None:
    """用 pdf_section_detector 做全文标题检测，补全 bookmark/body_heading 漏掉的节。

    将检测到的 section 以低优先级 (body_heading 同级) 加入 candidates，
    后续由 _dedupe_section_candidates 按 source_rank 去重。
    """
    if not text_by_page:
        return
    try:
        from src.report.fact_extractors.pdf_section_detector import detect_sections
    except ImportError:
        return

    # 拼接全文
    sorted_pages = sorted(text_by_page.items())
    full_text = "\n".join(str(text) for _, text in sorted_pages)
    if len(full_text) < 200:
        return

    detected = detect_sections(full_text, market=market)
    if not detected:
        return

    # 对每个检测到的 section，估算它在哪一页
    existing_types = {c["section_type"] for c in candidates}
    for section_type, section_text in detected.items():
        if section_type in existing_types:
            continue
        if not section_text or len(str(section_text).strip()) < 100:
            continue

        # 估算该 section 在全文中出现的大致页码
        text_start = full_text.find(str(section_text)[:80])
        if text_start < 0:
            continue
        # 累计字符数到该位置，估算页号
        cum_chars = 0
        approx_page = 1
        for page_num, page_text in sorted_pages:
            page_len = len(str(page_text or ""))
            if cum_chars + page_len >= text_start:
                approx_page = page_num
                break
            cum_chars += page_len

        candidates.append({
            "page": approx_page,
            "section_type": section_type,
            "title": section_type,
            "anchor_source": "body_heading",
            "anchor_confidence": 0.7,
            "matched_heading": "",
            "matched_toc_line": "",
        })


def _fallback_quarterly_map(
    candidates: list[dict[str, Any]],
    text_by_page: dict[int, str],
    max_page: int,
) -> None:
    """短文档后备：当标题匹配找不到足够 section 时，按典型季度报告页面分布分配。

    中国 A 股季度报告的标准页面分布:
      Pages 1-2:  公司基本信息 + 主要财务数据 → business_overview
      Pages 3-4:  销售情况 + 股东信息          → business_overview（续）
      Pages 5:    其他提醒事项                 → management_discussion
      Pages 6-12: 财务报表                     → financial_statements
    """
    if max_page <= 10:
        return  # 太短，不做切割

    existing_types = {c["section_type"] for c in candidates}
    page_text_len = {p: len(str(t or "")) for p, t in text_by_page.items()}

    # 按文本量估算每部分的主要起始页
    # 前三页通常是公司信息 + 财务摘要
    if "business_overview" not in existing_types:
        candidates.append({
            "page": 1,
            "section_type": "business_overview",
            "title": "业务概览",
            "anchor_source": "body_heading",
            "anchor_confidence": 0.5,
            "matched_heading": "",
            "matched_toc_line": "",
        })

    # 最后几页通常是财务报表 — 寻找财务数据开始页
    if "financial_statements" not in existing_types:
        # 从第 5 页开始往后找大段数字文本作为财报开始
        fs_page = max(5, max_page - 8)
        candidates.append({
            "page": fs_page,
            "section_type": "financial_statements",
            "title": "财务报告",
            "anchor_source": "body_heading",
            "anchor_confidence": 0.5,
            "matched_heading": "",
            "matched_toc_line": "",
        })

    # 如果中间有备注/提醒页
    if "management_discussion" not in existing_types:
        # 找到 financial_statements 的起始页（如果已存在），放在财报之前
        fs_start = 999
        for c in candidates:
            if c["section_type"] == "financial_statements":
                fs_start = min(fs_start, int(c.get("page", 999)))
        mgmt_page = max(fs_start - 2, 4) if fs_start < 999 else 4
        for p in range(4, min(max_page, fs_start)):
            t = str(text_by_page.get(p, "") or "")
            if "提醒" in t or "其他" in t:
                mgmt_page = p
                break
        if mgmt_page < max_page:
            candidates.append({
                "page": mgmt_page,
                "section_type": "management_discussion",
                "title": "管理层讨论与分析",
                "anchor_source": "body_heading",
                "anchor_confidence": 0.5,
                "matched_heading": "",
                "matched_toc_line": "",
            })


def _is_business_overview_text(text: str) -> bool:
    value = str(text or "")
    lowered = value.lower()
    if any(term.lower() in lowered for term in BUSINESS_NEGATIVE_TERMS):
        return False
    return any(term.lower() in lowered for term in BUSINESS_POSITIVE_TERMS)


# ── Language-agnostic content quality helpers ──────────────────────────
# These replace the old CJK-ratio heuristic which incorrectly discarded
# genuine English content from Chinese companies with English annual reports.


def _is_toc_text(text: str) -> bool:
    """Detect table-of-contents / navigation text in any language.

    Looks for line-level patterns common to PDF TOC pages:
      - "Section X" headings
      - Dotted leaders followed by page numbers
      - Standalone page numbers
      - "Contents" / "目录" headers

    Returns True when >= 30% of lines match TOC patterns.
    """
    lines = [l.strip() for l in str(text or "").split("\n") if l.strip()]
    if not lines:
        return False
    toc_count = 0
    for line in lines:
        if re.search(r"(?i)^Section\s+(?:[IVXLCDM]+\b|\d+)", line):
            toc_count += 1
        elif re.search(r"[\.…]{4,}\s*\d+\s*$", line) and len(line) > 30:
            toc_count += 1
        elif re.match(r"^\d{1,3}\s*$", line):
            toc_count += 1
        elif re.match(r"(?i)^contents?\s*$", line):
            toc_count += 1
        elif re.search(r"(?i)(?:目\s*录|table\s+of\s+contents)", line):
            toc_count += 1
    return (toc_count / max(len(lines), 1)) >= 0.25


def _is_boilerplate_text(text: str) -> bool:
    """Detect disclaimer / boilerplate text rather than actual section content.

    English boilerplate signals:
      - Forward-looking statements
      - Director attendance / board meeting formalities
      - Legal disclaimers ("make no representation", "material omissions")
      - Virtual promises boilerplate
    Chinese boilerplate signals:
      - "没有虚假记载、误导性陈述或重大遗漏"
      - "负责人" + "保证" + "真实性"
    """
    lowered = str(text or "").lower()

    english_boilerplate = [
        r"forward.{0,30}statement",
        r"directors?\s+attend",
        r"(?:make|makes?)\s+no\s+representation",
        r"(?:false|material)\s+(?:records?|omissions?)",
        r"virtual\s+promises?",
        r"(?:responsible|liability)\s+for\s+truthfulness",
        r"audit\s+committee",
        r"individually\s+and\s+together\s+be\s+legally\s+liable",
        r"does\s+not\s+constitute",
        r"independent\s+auditor",
        r"risk\s+awareness",
        r"forward-looking",
    ]
    chinese_boilerplate = [
        r"没有虚假记载",
        r"误导性陈述",
        r"重大遗漏",
        r"保证.*真实性",
        r"负责人.*保证.*准确",
        r"承担.*法律责任",
    ]

    combined = english_boilerplate + chinese_boilerplate
    return any(re.search(p, lowered) for p in combined)


def _compact_pdf_summary(text: str, max_chars: int = 520) -> str:
    value = _strip_pdf_summary_boilerplate(str(text or ""))
    value = re.sub(r"\s+", " ", value).strip()
    if not value:
        return ""
    sentences = re.split(r"(?<=[。！？.!?])\s+", value)
    picked: list[str] = []
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        picked.append(sentence)
        if len(" ".join(picked)) >= max_chars or len(picked) >= 4:
            break
    summary = " ".join(picked).strip() or value[:max_chars]
    return summary[:max_chars].strip()


def _strip_pdf_summary_boilerplate(text: str) -> str:
    value = strip_pdf_boilerplate(str(text or ""))
    patterns = [
        r"[\u4e00-\u9fffA-Za-z0-9（）()\s·,\.-]{0,80}\d{4}\s*年\s*年度报告",
        r"\bForm\s+10-[KQ]/?A?\b",
        r"\bAnnual\s+Report\b",
        r"第[一二三四五六七八九十百\d]+[章节]\s*(?:释义|公司简介和主要财务指标|管理层讨论与分析|公司治理|财务报告|主营业务|业务概览)?\s*",
        r"Item\s+\d+[A-Z]?\.\s*(?:Business|Risk Factors|Management'?s Discussion and Analysis|Financial Statements)?\s*",
        r"^[一二三四五六七八九十\d]+[、.．]\s*",
    ]
    for pattern in patterns:
        value = re.sub(pattern, " ", value, flags=re.I)
    return value.strip()


def _looks_like_table(text: str, page_count: int = 0) -> bool:
    """判断文本块是否像表格。

    Args:
        text: 文本块
        page_count: PDF 总页数。≤20 页（短文档如季度报告）使用更严格阈值，避免
                    将财务叙述性内容误判为表格导致 text_chunks 为空。

    Returns:
        True 如果识别为表格
    """
    line = str(text or "").strip()
    digit_count = len(re.findall(r"\d", line))
    digit_threshold = SHORT_DOC_TABLE_DIGIT_THRESHOLD if (page_count and page_count <= 20) else LONG_DOC_TABLE_DIGIT_THRESHOLD

    # —— 条件1: 显式表格标题（资产负债表/利润表/现金流量表）+ 足够数字 → 表格
    specific_table_pattern = re.compile(r"(资产负债表|利润表|现金流量表|balance sheet|income statement|cash flow statement)", re.I)
    if specific_table_pattern.search(line) and digit_count >= digit_threshold:
        return True

    # —— 条件2: 管道符分隔（CSV-like）→ 表格
    if "|" in line and len(line.split("|")) >= 3:
        return True

    # —— 条件3: 多空格分隔 + 大量数字 → 表格
    # 要求多列布局（多空格分隔）且有数字，对短文档要求更多列
    multi_col = re.split(r"\s{2,}", line)
    min_cols = 4 if (page_count and page_count <= 20) else 3
    if len(multi_col) >= min_cols and re.search(r"\b\d[\d,\.]*\b", line) and digit_count >= digit_threshold:
        return True

    return False


def _matches_patterns(text: str, patterns: Iterable[str]) -> bool:
    cleaned = str(text or "").strip()
    return any(re.search(str(pattern), cleaned, re.I) for pattern in patterns)


def _verify_heading_near_page(
    text_by_page: dict[int, str],
    target_page: int,
    section_type: str,
    schema: dict[str, dict[str, Any]],
    toc_pages: set[int],
) -> dict[str, Any] | None:
    config = schema.get(section_type, {})
    for page in range(max(1, target_page - 2), target_page + 3):
        if page in toc_pages:
            continue
        text = str(text_by_page.get(page) or "")
        for line in [row.strip() for row in text.splitlines() if row.strip()][:120]:
            if _looks_like_heading(line) and _matches_patterns(line, config.get("heading_patterns", [])):
                return {"page": page, "line": line}
    return None


def _correct_bookmark_pages(
    candidates: list[dict[str, Any]],
    text_by_page: dict[int, str],
    schema: dict[str, dict[str, Any]],
    toc_pages: set[int],
) -> list[dict[str, Any]]:
    """校正书签页码：扫描全文定位 section 标题的实际页码。

    CNINFO PDF 的书签经常指向目录页（第 2-4 页）而非正文起始页，
    导致 section_map 完全错误。此函数通过全文扫描标题文本来
    找到每个 section 真正出现的页面。

    对已正确标注的 PDF（如 SEC 10-K 书签指向 Item 正文页）
    不会产生副作用，因为 heading text 在书签页就能找到。

    Args:
        candidates: 候选列表（来自 bookmark / printed_toc / body_heading）
        text_by_page: 全量页面文本 {page_num: text}
        schema: 当前市场的 section schema
        toc_pages: 目录页集合（跳过这些页面的标题匹配）

    Returns:
        已校正页码的候选列表
    """
    max_page = max(text_by_page)
    corrected: list[dict[str, Any]] = []

    for cand in candidates:
        source = str(cand.get("anchor_source") or "")
        # 只校正 bookmark 来源的候选；body_heading 本身来自正文检测
        if source != "bookmark":
            corrected.append(cand)
            continue

        bk_page = int(cand["page"])
        section_type = str(cand["section_type"])
        config = schema.get(section_type, {})
        heading_text = str(cand.get("matched_heading") or "").strip()

        # 第一步：检查 bookmark 页本身是否包含标题
        # 如果包含 → 书签页码正确，无需校正
        if _heading_appears_on_page(text_by_page, bk_page, heading_text, config, toc_pages):
            corrected.append(cand)
            continue

        # 第二步：书签页没找到标题 → 扫描所有页面定位
        found_page = _find_heading_page(
            text_by_page, bk_page, heading_text, config, toc_pages, max_page,
        )

        if found_page and found_page != bk_page:
            corrected.append({**cand, "page": found_page, "anchor_source": "bookmark_corrected", "anchor_confidence": 0.95})
        else:
            corrected.append(cand)

    return corrected


def _heading_appears_on_page(
    text_by_page: dict[int, str],
    page: int,
    heading_text: str,
    config: dict[str, Any],
    toc_pages: set[int],
) -> bool:
    """检查指定页面上是否包含给定的 section 标题。

    排除 TOC 行（``..... 53`` 格式），避免 TOC 中的"第十节 财务报告 ...... 53"
    被误判为正文标题而跳过页码校正。
    """
    if page in toc_pages:
        return False
    page_text = str(text_by_page.get(page) or "")
    lines = [line.strip() for line in page_text.splitlines() if line.strip()]
    for line in lines[:60]:
        # 跳过 TOC 格式行 (... 数字 或 …… 数字)
        if re.search(r"[\.…]{3,}\s*\d+\s*$", line):
            continue
        if _looks_like_heading(line) and _matches_patterns(line, config.get("heading_patterns", []) or []):
            return True
        if heading_text and heading_text in line:
            return True
    return False


def _find_heading_page(
    text_by_page: dict[int, str],
    start_page: int,
    heading_text: str,
    config: dict[str, Any],
    toc_pages: set[int],
    max_page: int,
) -> int | None:
    """从 bookmark 页往后扫描，找到标题实际出现的页面。

    搜索策略：
      1. 先从 bookmark 页向前扫描（±3 页，覆盖小幅偏移）
      2. 再从 bookmark 页向后扫描所有剩余页面（覆盖大幅偏移）
      3. 最后从第 1 页扫描到 bookmark 页（覆盖反向偏移）
    """
    patterns = config.get("heading_patterns", []) or []

    # Phase 1: ±3 pages（小幅偏移，兼容已有逻辑）
    for page in range(max(1, start_page - 3), min(max_page, start_page + 3) + 1):
        if page in toc_pages:
            continue
        text = str(text_by_page.get(page) or "")
        for line in [row.strip() for row in text.splitlines() if row.strip()][:200]:
            if re.search(r"[\.…]{3,}\s*\d+\s*$", line):
                continue
            if _looks_like_heading(line) and _matches_patterns(line, patterns):
                return page

    # Phase 2: start_page → max_page（大幅偏移，CNINFO 典型场景）
    for page in range(start_page, max_page + 1):
        if page in toc_pages:
            continue
        text = str(text_by_page.get(page) or "")
        for line in [row.strip() for row in text.splitlines() if row.strip()][:200]:
            if re.search(r"[\.…]{3,}\s*\d+\s*$", line):
                continue
            if _looks_like_heading(line) and _matches_patterns(line, patterns):
                return page

    # Phase 3: 1 → start_page（反向偏移）
    for page in range(1, start_page):
        if page in toc_pages:
            continue
        text = str(text_by_page.get(page) or "")
        for line in [row.strip() for row in text.splitlines() if row.strip()][:200]:
            if re.search(r"[\.…]{3,}\s*\d+\s*$", line):
                continue
            if _looks_like_heading(line) and _matches_patterns(line, patterns):
                return page

    return None


def _looks_like_heading(line: str) -> bool:
    text = str(line or "").strip()
    if not text or len(text) > 120:
        return False
    if re.search(r"^(第[一二三四五六七八九十百0-9]+[章节]|item\s+\d+[a-z]?\.?)", text, re.I):
        return True
    if re.search(r"(business|risk factors|management discussion|corporate governance|财务报告|公司治理|股东情况|风险提示|管理层讨论)", text, re.I):
        return True
    return False


def _dedupe_section_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_section: dict[str, dict[str, Any]] = {}
    source_rank = {"bookmark": 4, "bookmark_corrected": 4, "printed_toc_verified": 3, "body_heading": 2, "printed_toc_unverified": 1}
    for row in candidates:
        section_type = str(row.get("section_type") or "")
        if not section_type:
            continue
        current = best_by_section.get(section_type)
        if current is None:
            best_by_section[section_type] = row
            continue
        current_rank = (source_rank.get(str(current.get("anchor_source")), 0), -int(current.get("page") or 9999))
        new_rank = (source_rank.get(str(row.get("anchor_source")), 0), -int(row.get("page") or 9999))
        if new_rank > current_rank:
            best_by_section[section_type] = row
    return list(best_by_section.values())


def _target_section_types(section_map: dict[str, dict[str, Any]], report_market: str) -> list[str]:
    preferred = list(get_section_schema(report_market).keys())
    output = [section for section in preferred if section in section_map]
    return output or preferred


def _pages_for_sections(
    text_by_page: dict[int, str],
    section_map: dict[str, dict[str, Any]],
    max_pages_per_section: int,
) -> dict[int, str]:
    if not section_map:
        return dict(list(text_by_page.items())[: max(1, int(max_pages_per_section))])
    pages: set[int] = set()
    limit = max(1, int(max_pages_per_section))
    for info in section_map.values():
        start, end = info.get("pages", (0, 0))
        start_i = int(start or 0)
        end_i = int(end or 0)
        for page in range(start_i, min(end_i, start_i + limit - 1) + 1):
            if page in text_by_page:
                pages.add(page)
    return {page: text_by_page[page] for page in sorted(pages)}


def _gap_summary(section_type: str, reason: str, symbol: str, period: str) -> dict[str, Any]:
    messages = {
        "business_overview": "已获取官方 PDF，但尚未稳定抽取主营业务、产品结构或业务分部章节，因此本节不直接展开业务画像。",
        "management_discussion": "已获取官方 PDF，但尚未稳定抽取管理层讨论与分析章节，因此本节不直接扩写经营解读。",
        "ownership_governance": "已获取官方 PDF，但尚未稳定抽取治理章节；若缺 proxy 或等价治理披露，本节保持 data_gap。",
        "shareholder_structure": "已获取官方 PDF，但尚未稳定抽取股份变动及股东情况章节，因此不编造股东结构结论。",
        "risk_factors": "已获取官方 PDF，但尚未稳定抽取风险提示章节，因此不输出伪确定性的风险条目。",
        "financial_statements": "已获取官方 PDF，但尚未稳定抽取财务报告正文，本节只保留结构化三表路径。",
    }
    if reason == "noise_only":
        messages = {
            key: value.replace("尚未稳定抽取", "候选片段主要是页眉、目录指针、重要提示或审计样板语，未能稳定抽取")
            for key, value in messages.items()
        }
    return {
        "section_type": section_type,
        "summary_zh": messages.get(section_type, "已获取官方 PDF，但该章节尚未形成可用于生成的摘要。"),
        "source_chunk_ids": [],
        "retrieval_scores": [],
        "anchor_source": "",
        "negative_filters_applied": [],
        "evidence_quality": "noise_only" if reason == "noise_only" else "missing",
        "usable_for_generation": False,
        "is_noise": True,
        "gap_reason": reason,
    }


def _gap_summary(section_type: str, reason: str, symbol: str, period: str) -> dict[str, Any]:
    messages = {
        "business_overview": "已获取官方 PDF，但未稳定抽取主营业务、产品结构或业务分部章节，因此本节保持数据缺口。",
        "management_discussion": "已获取官方 PDF，但未稳定抽取管理层讨论与分析章节，因此本节不直接扩写经营解读。",
        "ownership_governance": "已获取官方 PDF，但未稳定抽取治理章节；若缺少 proxy/治理披露，本节保持 data_gap。",
        "shareholder_structure": "已获取官方 PDF，但未稳定抽取股份变动及股东情况章节，因此不编造股东结构结论。",
        "risk_factors": "已获取官方 PDF，但未稳定抽取风险提示章节，因此不输出伪确定性的风险条目。",
        "financial_statements": "已获取官方 PDF，但未稳定抽取财务报告正文，本节只保留结构化三表路径。",
    }
    if reason == "noise_only":
        messages = {
            key: value.replace("未稳定抽取", "候选片段主要是页眉、目录指针、重要提示、乱码或审计模板，未能稳定抽取")
            for key, value in messages.items()
        }
    if reason == "mojibake":
        messages = {key: "已获取官方 PDF，但候选章节存在乱码，已阻断进入正文；请检查 PDF 解码/抽取链路。" for key in messages}
    return {
        "section_type": section_type,
        "summary_zh": messages.get(section_type, "已获取官方 PDF，但该章节尚未形成可用于生成的摘要。"),
        "source_chunk_ids": [],
        "retrieval_scores": [],
        "anchor_source": "",
        "negative_filters_applied": [],
        "evidence_quality": "noise_only" if reason in {"noise_only", "mojibake"} else "missing",
        "usable_for_generation": False,
        "is_noise": True,
        "gap_reason": reason,
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    payload = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    path.write_text(payload + ("\n" if rows else ""), encoding="utf-8")


def _empty_audit(pdf_url: str, local_pdf_path: str | Path, symbol: str, period: str, failure_reason: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "period": period,
        "pdf_url": pdf_url,
        "local_pdf_path": str(local_pdf_path),
        "report_market": "generic",
        "embedding_model": resolve_embedding_model("generic").get("embedding_model", ""),
        "embedding_backend": "not_loaded",
        "section_schema_version": SECTION_SCHEMA_VERSION,
        "page_count": 0,
        "extracted_page_count": 0,
        "toc_found": False,
        "section_map": {},
        "section_coverage": {},
        "candidate_chunks_count": 0,
        "noise_filtered_count": 0,
        "usable_chunk_count": 0,
        "retrieval_meta": {},
        "fallbacks_used": [],
        "top_rejection_reasons": {},
        "failure_reason": failure_reason,
    }


def _build_audit(
    pdf_url: str,
    local_pdf_path: str | Path,
    symbol: str,
    period: str,
    page_count: int,
    extracted_page_count: int,
    toc_found: bool,
    section_map: dict[str, dict[str, Any]],
    chunks: list[dict[str, Any]],
    failure_reason: str,
    report_market: str,
    retrieval_meta: dict[str, Any],
    fallbacks_used: list[str],
    embedding_route: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rejection_counts: dict[str, int] = {}
    section_coverage: dict[str, dict[str, int]] = {}
    for chunk in chunks:
        section_type = str(chunk.get("section_type") or "other")
        bucket = section_coverage.setdefault(section_type, {"candidate_chunks_count": 0, "usable_chunk_count": 0, "noise_filtered_count": 0})
        bucket["candidate_chunks_count"] += 1
        if chunk.get("usable_for_generation"):
            bucket["usable_chunk_count"] += 1
        else:
            bucket["noise_filtered_count"] += 1
            reason = str(chunk.get("rejection_reason") or "unknown")
            rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
    route = embedding_route or resolve_embedding_model(report_market, "")
    embedding_backend = str(route.get("embedding_backend") or "")
    for meta in retrieval_meta.values():
        if isinstance(meta, dict) and meta.get("embedding_backend"):
            embedding_backend = str(meta.get("embedding_backend") or embedding_backend)
            if embedding_backend == "sentence_transformers":
                break
    return {
        "symbol": symbol,
        "period": period,
        "pdf_url": pdf_url,
        "local_pdf_path": str(local_pdf_path),
        "report_market": report_market,
        "embedding_model": route.get("embedding_model", ""),
        "embedding_backend": embedding_backend,
        "section_schema_version": SECTION_SCHEMA_VERSION,
        "page_count": page_count,
        "extracted_page_count": extracted_page_count,
        "toc_found": toc_found,
        "section_map": {
            key: {
                "title": value.get("title", ""),
                "pages": list(value.get("pages", [])),
                "page_count": value.get("page_count", 0),
                "anchor_source": value.get("anchor_source", ""),
                "anchor_confidence": value.get("anchor_confidence", 0.0),
                "matched_heading": value.get("matched_heading", ""),
                "matched_toc_line": value.get("matched_toc_line", ""),
            }
            for key, value in section_map.items()
            if isinstance(value, dict)
        },
        "section_coverage": section_coverage,
        "candidate_chunks_count": len(chunks),
        "noise_filtered_count": sum(1 for chunk in chunks if not chunk.get("usable_for_generation")),
        "usable_chunk_count": sum(1 for chunk in chunks if chunk.get("usable_for_generation")),
        "retrieval_meta": retrieval_meta,
        "fallbacks_used": fallbacks_used,
        "fallback_reason": route.get("fallback_reason", "") or failure_reason,
        "top_rejection_reasons": dict(sorted(rejection_counts.items(), key=lambda item: item[1], reverse=True)[:8]),
        "failure_reason": failure_reason,
    }


def _merge_audits(audits: list[dict[str, Any]], symbol: str, period: str) -> dict[str, Any]:
    if not audits:
        return _empty_audit("", "", symbol, period, "no_cached_pdf")
    if len(audits) == 1:
        return audits[0]
    merged = _empty_audit("", "", symbol, period, "")
    merged["pdf_url"] = [audit.get("pdf_url", "") for audit in audits]
    merged["local_pdf_path"] = [audit.get("local_pdf_path", "") for audit in audits]
    merged["page_count"] = sum(int(audit.get("page_count") or 0) for audit in audits)
    merged["extracted_page_count"] = sum(int(audit.get("extracted_page_count") or 0) for audit in audits)
    merged["toc_found"] = any(bool(audit.get("toc_found")) for audit in audits)
    merged["report_market"] = next((str(audit.get("report_market")) for audit in audits if audit.get("report_market")), "generic")
    merged["section_map"] = {key: value for audit in audits for key, value in dict(audit.get("section_map", {})).items()}
    merged["section_coverage"] = {key: value for audit in audits for key, value in dict(audit.get("section_coverage", {})).items()}
    merged["candidate_chunks_count"] = sum(int(audit.get("candidate_chunks_count") or 0) for audit in audits)
    merged["noise_filtered_count"] = sum(int(audit.get("noise_filtered_count") or 0) for audit in audits)
    merged["usable_chunk_count"] = sum(int(audit.get("usable_chunk_count") or 0) for audit in audits)
    merged["retrieval_meta"] = {key: value for audit in audits for key, value in dict(audit.get("retrieval_meta", {})).items()}
    merged["fallbacks_used"] = sorted(set(item for audit in audits for item in list(audit.get("fallbacks_used", []))))
    rejection_counts: dict[str, int] = {}
    for audit in audits:
        for reason, count in dict(audit.get("top_rejection_reasons", {})).items():
            rejection_counts[str(reason)] = rejection_counts.get(str(reason), 0) + int(count or 0)
    merged["top_rejection_reasons"] = dict(sorted(rejection_counts.items(), key=lambda item: item[1], reverse=True)[:8])
    failures = [str(audit.get("failure_reason") or "") for audit in audits if str(audit.get("failure_reason") or "")]
    merged["failure_reason"] = "; ".join(failures)
    return merged


# ── PDF 页文本清洗：过滤书签偏移带来的非预期 Unicode 字符 ──

# 中文年报可预期的合法 Unicode 块（CJK + Latin + 标点 + 符号 + 数字）
_ALLOWED_UNICODE_BLOCKS = [
    (0x0000, 0x007F),   # Basic Latin (ASCII)
    (0x0080, 0x00FF),   # Latin-1 Supplement
    (0x0100, 0x024F),   # Latin Extended
    (0x02B0, 0x02FF),   # Spacing Modifier Letters
    (0x0300, 0x036F),   # Combining Diacritical Marks
    (0x0370, 0x03FF),   # Greek & Coptic
    (0x2000, 0x206F),   # General Punctuation
    (0x2070, 0x209F),   # Superscripts and Subscripts
    (0x20A0, 0x20CF),   # Currency Symbols
    (0x2100, 0x214F),   # Letterlike Symbols
    (0x2150, 0x218F),   # Number Forms
    (0x2190, 0x21FF),   # Arrows
    (0x2200, 0x22FF),   # Mathematical Operators
    (0x2300, 0x23FF),   # Miscellaneous Technical
    (0x2460, 0x24FF),   # Enclosed Alphanumerics
    (0x2500, 0x257F),   # Box Drawing
    (0x2580, 0x259F),   # Block Elements
    (0x25A0, 0x25FF),   # Geometric Shapes
    (0x2600, 0x26FF),   # Miscellaneous Symbols
    (0x2700, 0x27BF),   # Dingbats
    (0x2E80, 0x2EFF),   # CJK Radicals Supplement
    (0x2F00, 0x2FDF),   # Kangxi Radicals
    (0x3000, 0x303F),   # CJK Symbols and Punctuation
    (0x3040, 0x309F),   # Hiragana
    (0x30A0, 0x30FF),   # Katakana
    (0x3100, 0x312F),   # Bopomofo
    (0x31A0, 0x31BF),   # Bopomofo Extended
    (0x31F0, 0x31FF),   # Katakana Phonetic Extensions
    (0x3200, 0x32FF),   # Enclosed CJK Letters and Months
    (0x3300, 0x33FF),   # CJK Compatibility
    (0x3400, 0x4DBF),   # CJK Unified Ideographs Extension A
    (0x4E00, 0x9FFF),   # CJK Unified Ideographs (核心中文)
    (0xF900, 0xFAFF),   # CJK Compatibility Ideographs
    (0xFE10, 0xFE1F),   # Vertical Forms
    (0xFE30, 0xFE4F),   # CJK Compatibility Forms
    (0xFE50, 0xFE6F),   # Small Form Variants
    (0xFF00, 0xFFEF),   # Halfwidth and Fullwidth Forms
]


def _in_allowed_block(char: str) -> bool:
    """检查单个字符是否属于中文年报可预期的合法 Unicode 块。"""
    code = ord(char)
    if code in (0x00A0, 0x200B, 0xFEFF):  # NBSP, ZWSP, BOM
        return True
    return any(lo <= code <= hi for lo, hi in _ALLOWED_UNICODE_BLOCKS)


def _clean_pdf_page_text(text: str) -> str:
    """清洗单页 PDF 文本。

    书签页码偏移时，section 页范围可能包含其他语言或错误编码的页面。
    此函数过滤不可预期的 Unicode 字符（如 Cyrillic、Georgian、Khmer
    等不会出现在中文年报中的 Unicode 块），防止乱码进入下游。
    """
    if not text:
        return ""
    cleaned = [c for c in text if c in "\n\r\t" or _in_allowed_block(c)]
    return "".join(cleaned)


def _normalize_report_market(report_type: str) -> str:
    raw = str(report_type or "").strip().lower()
    mapping = {"a_share": "cn_a", "cn_a": "cn_a", "sec": "us", "us": "us", "hk": "hk"}
    return mapping.get(raw, "generic")


_RETRIEVAL_CONFIG_CACHE: dict[str, Any] | None = None


def _load_retrieval_config() -> dict[str, Any]:
    global _RETRIEVAL_CONFIG_CACHE
    if _RETRIEVAL_CONFIG_CACHE is not None:
        return _RETRIEVAL_CONFIG_CACHE
    candidates = [
        Path("configs/retrieval.yaml"),
        Path(__file__).resolve().parents[2] / "configs" / "retrieval.yaml",
    ]
    for path in candidates:
        try:
            if path.exists():
                _RETRIEVAL_CONFIG_CACHE = load_config(path)
                return _RETRIEVAL_CONFIG_CACHE
        except Exception:
            continue
    _RETRIEVAL_CONFIG_CACHE = {}
    return _RETRIEVAL_CONFIG_CACHE


def _dedupe_text(values: Iterable[str]) -> list[str]:
    output: list[str] = []
    for value in values:
        row = str(value or "").strip()
        if row and row not in output:
            output.append(row)
    return output
