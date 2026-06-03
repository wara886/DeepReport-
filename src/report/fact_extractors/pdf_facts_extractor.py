"""PDF facts extractor — 从 PDF chunk 中提取结构化事实。

目标：
    终结 raw PDF paste。当前业务概览直接贴年报段落原文，
    因为 LLM 收到的 evidence 是 raw chunk。这个模块把
    chunk 内容转为结构化 facts，LLM 基于 facts 写研报语言段落。

用法：
    from src.report.fact_extractors.pdf_facts_extractor import extract_section_facts

    pdf_sections = [...]  # 从 orchestrator 获取
    facts = extract_section_facts(pdf_sections, market="cn_a")
    # facts["business_overview"] = {
    #     "products": ["茅台酒", "系列酒"],
    #     "core_competitiveness": ["品质", "品牌", "工艺", "环境", "文化"],
    #     "revenue": "1720亿",
    #     "business_model": "白酒生产销售",
    # }
"""

from __future__ import annotations

import re
from typing import Any


# ── 泛词过滤：这些词不单独作为 facts 输出 ────────
# 它们可能是 pattern 匹配到的上下文词，不是真正的业务特征
_GENERIC_WORDS = {
    "产品", "渠道", "核心竞争力", "质量", "技术", "创新", "研发",
    "销售", "生产", "发展", "管理", "业务", "服务", "市场",
    "战略", "规划", "计划", "目标", "方向", "举措", "措施",
    "推进", "深化", "风险", "影响", "波动", "成本", "费用", "利润",
    "消费", "需求", "价格", "库存", "原材料",
}


def _filter_generic(items: set[str]) -> list[str]:
    """过滤泛词，按长度降序排列（优先保留具体词）。"""
    meaningful = [w for w in items if w not in _GENERIC_WORDS and len(w) >= 2]
    return sorted(meaningful, key=lambda x: -len(x))


# ── Section-specific extraction patterns ───────────

# 业务概览 facts
_BUSINESS_PRODUCT_RE = re.compile(
    r"(茅台酒|系列酒|茅台|王子酒|迎宾酒|酱香白酒|酱香|白酒|葡萄酒|啤酒|饮料)"
)
_BUSINESS_CHANNEL_RE = re.compile(
    r"(直销|批发代理|i茅台|经销商|专卖店|电商平台|超市|终端门店|渠道)"
)
_BUSINESS_COMPETITIVENESS_RE = re.compile(
    r"(品质|品牌|工艺|环境|文化|五大核心竞争力|核心竞争力|技术领先|创新驱动)"
)
_BUSINESS_MODEL_RE = re.compile(
    r"(生产|销售|经营模式|主营业务|业务结构|产品结构)"
)
_BUSINESS_REVENUE_RE = re.compile(
    r"(?:收入|营收|营业额|销售)(?:总额|合计)?[：:\s]*(\d[\d,.]*\s*[万亿千百元美元]*)"
)

# 公司治理 facts
_GOVERNANCE_BOARD_RE = re.compile(
    r"(董事会|监事会|独立董事|董事|高管|管理层)"
)
_GOVERNANCE_SHAREHOLDER_RE = re.compile(
    r"(控股股东|实际控制人|前十名股东|大股东|股权结构|持股比例)"
)
_GOVERNANCE_CONTROL_RE = re.compile(
    r"(内控|内部控制|信息披露|公司治理|合规)"
)

# 风险 facts
_RISK_OFFICIAL_RE = re.compile(
    r"(风险提示|可能面对的风险|风险因素|重大风险)"
)
_RISK_INDUSTRY_RE = re.compile(
    r"(行业风险|市场风险|竞争风险|政策风险|监管风险|消费需求|价格波动|库存管理|原材料)"
)

# 管理层讨论 facts
_MDA_STRATEGY_RE = re.compile(
    r"(战略|规划|发展|计划|目标|方向|举措|措施|推进|深化)"
)
_MDA_OPERATION_RE = re.compile(
    r"(经营情况|经营业绩|业务进展|生产|销售|成本|费用|利润|毛利)"
)


def extract_section_facts(
    pdf_sections: list[dict[str, Any]],
    market: str = "cn_a",
) -> dict[str, dict[str, Any]]:
    """从 PDF section summaries 中提取结构化事实。

    Args:
        pdf_sections: PDF section summaries 列表，每项含 section_type、summary_zh、text_clean
        market: 市场类型

    Returns:
        按 section_type 组织的 facts dict:
        {
            "business_overview": {
                "products": [...],
                "channels": [...],
                "core_competitiveness": [...],
                "business_model": "...",
                "revenue": "...",
            },
            "ownership_governance": {...},
            "risk_factors": {...},
            "management_discussion": {...},
        }
    """
    if not pdf_sections:
        return {}

    # 按 section_type 分组
    grouped: dict[str, list[str]] = {}
    for sec in pdf_sections:
        st = str(sec.get("section_type") or "other")
        text = str(sec.get("summary_zh") or sec.get("text_clean") or sec.get("text") or "")
        if len(text) < 30:
            continue
        grouped.setdefault(st, []).append(text)

    facts: dict[str, dict[str, Any]] = {}

    for section_type, texts in grouped.items():
        combined = "\n".join(texts)
        extractor = _get_extractor(section_type)
        if extractor:
            facts[section_type] = extractor(combined, market=market)

    return facts


def _get_extractor(section_type: str):
    """根据 section 类型返回对应的事实提取函数。"""
    extractors = {
        "business_overview": _extract_business_facts,
        "ownership_governance": _extract_governance_facts,
        "shareholder_structure": _extract_governance_facts,
        "risk_factors": _extract_risk_facts,
        "management_discussion": _extract_mda_facts,
        "financial_statements": _extract_financial_facts,
    }
    return extractors.get(section_type, _extract_generic_facts)


def _extract_business_facts(text: str, market: str = "") -> dict[str, Any]:
    """提取业务概览 facts。"""
    facts: dict[str, Any] = {}

    # 产品
    products = _filter_generic(set(_BUSINESS_PRODUCT_RE.findall(text)))
    if products:
        facts["products"] = products[:5]

    # 渠道
    channels = _filter_generic(set(_BUSINESS_CHANNEL_RE.findall(text)))
    if channels:
        facts["channels"] = channels[:5]

    # 核心竞争力
    competitiveness = _filter_generic(set(_BUSINESS_COMPETITIVENESS_RE.findall(text)))
    if competitiveness:
        facts["core_competitiveness"] = competitiveness[:5]

    # 收入
    revenue_match = _BUSINESS_REVENUE_RE.search(text)
    if revenue_match:
        facts["revenue"] = revenue_match.group(1).strip()

    # 经营模式
    model_match = _BUSINESS_MODEL_RE.search(text)
    if model_match:
        sentences = text.split("。")
        for s in sentences:
            if model_match.search(s):
                cleaned = s.strip().replace("经营模式", "").replace("主营业务", "").replace("业务结构", "").strip()
                if cleaned:
                    facts["business_model"] = cleaned[:120]
                break

    return facts


def _extract_governance_facts(text: str, market: str = "") -> dict[str, Any]:
    """提取公司治理 facts。"""
    facts: dict[str, Any] = {}

    board = _filter_generic(set(_GOVERNANCE_BOARD_RE.findall(text)))
    if board:
        facts["governance_bodies"] = board[:5]

    shareholders = _filter_generic(set(_GOVERNANCE_SHAREHOLDER_RE.findall(text)))
    if shareholders:
        facts["shareholder_info"] = shareholders[:5]

    control = _filter_generic(set(_GOVERNANCE_CONTROL_RE.findall(text)))
    if control:
        facts["internal_control"] = control[:3]

    return facts


def _extract_risk_facts(text: str, market: str = "") -> dict[str, Any]:
    """提取风险 facts。"""
    facts: dict[str, Any] = {}

    official_matches = _RISK_OFFICIAL_RE.findall(text)
    facts["has_official_risk_section"] = bool(official_matches)

    industry_risks = _filter_generic(set(_RISK_INDUSTRY_RE.findall(text)))
    if industry_risks:
        facts["industry_risks"] = industry_risks[:8]

    # 提取风险描述句子
    risk_sentences = []
    for s in text.split("。"):
        if any(word in s for word in ["风险", "影响", "波动", "不确定", "挑战", "竞争"]):
            cleaned = s.strip().replace("风险提示", "").replace("可能面对的风险", "").strip()
            if cleaned and len(cleaned) > 10:
                risk_sentences.append(cleaned[:100])
    if risk_sentences:
        facts["risk_descriptions"] = risk_sentences[:3]

    return facts


def _extract_mda_facts(text: str, market: str = "") -> dict[str, Any]:
    """提取管理层讨论 facts。"""
    facts: dict[str, Any] = {}

    strategy = _filter_generic(set(_MDA_STRATEGY_RE.findall(text)))
    if strategy:
        facts["strategic_focus"] = strategy[:5]

    operations = _filter_generic(set(_MDA_OPERATION_RE.findall(text)))
    if operations:
        facts["operations"] = operations[:5]

    # 提取数字类经营数据
    number_patterns = [
        (r"(?:收入|营收)[：:\s]*(\d[\d,.]*\s*[万亿千百元美元亿]*)", "revenue"),
        (r"(?:利润|净利润)[：:\s]*(\d[\d,.]*\s*[万亿千百元美元亿]*)", "profit"),
        (r"(?:增长|增速)[：:\s]*(\d+\.?\d*%)", "growth_rate"),
    ]
    for pattern, key in number_patterns:
        match = re.search(pattern, text)
        if match:
            facts[key] = match.group(1).strip()

    return facts


def _extract_financial_facts(text: str, market: str = "") -> dict[str, Any]:
    """提取财务 facts。"""
    facts: dict[str, Any] = {
        "has_financial_data": True,
    }

    # 提取关键财务指标
    patterns = [
        (r"(?:总资产|资产总计)[：:\s]*(\d[\d,.]*\s*[万亿千百元美元亿]*)", "total_assets"),
        (r"(?:总负债|负债合计)[：:\s]*(\d[\d,.]*\s*[万亿千百元美元亿]*)", "total_liabilities"),
        (r"(?:净资产|股东权益|权益合计)[：:\s]*(\d[\d,.]*\s*[万亿千百元美元亿]*)", "equity"),
        (r"(?:收入|营收|营业收入)[：:\s]*(\d[\d,.]*\s*[万亿千百元美元亿]*)", "revenue"),
        (r"(?:净利润|归母净利润)[：:\s]*(\d[\d,.]*\s*[万亿千百元美元亿]*)", "net_profit"),
        (r"(?:毛利率)[：:\s]*(\d+\.?\d*)", "gross_margin"),
        (r"(?:净利率)[：:\s]*(\d+\.?\d*)", "net_margin"),
        (r"(?:经营现金流|经营活动)[：:\s]*(\d[\d,.]*\s*[万亿千百元美元亿]*)", "operating_cashflow"),
    ]
    for pattern, key in patterns:
        match = re.search(pattern, text)
        if match:
            facts[key] = match.group(1).strip()

    return facts


def _extract_generic_facts(text: str, market: str = "") -> dict[str, Any]:
    """通用 facts 提取（fallback）。"""
    facts: dict[str, Any] = {}

    # 提取所有数字指标
    numbers = re.findall(r"(\d[\d,.]*\s*[万亿千百元美元%]*)", text)
    if numbers:
        facts["key_metrics"] = numbers[:5]

    # 提取关键主题词（中英文词语 2-4 字）
    keywords = re.findall(r"[一-鿿]{2,6}", text)
    word_freq: dict[str, int] = {}
    for w in keywords:
        word_freq[w] = word_freq.get(w, 0) + 1
    common_words = {"公司", "报告", "企业", "本期", "年度", "以上", "以下", "亿元", "万元", "人民币"}
    meaningful = sorted(
        [(freq, word) for word, freq in word_freq.items() if word not in common_words and freq >= 2],
        reverse=True,
    )
    if meaningful:
        facts["key_topics"] = [word for freq, word in meaningful[:8]]

    return facts


# ── 将 facts 注入 section dossiers ────────────────

def inject_facts_into_dossiers(
    dossiers: dict[str, Any],
    facts: dict[str, dict[str, Any]],
    audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """将提取的结构化 facts 注入 section dossiers 的 suggested_paragraphs。

    这样 LLM 收到 dossier 时能看到结构化事实，而不是 raw PDF paste。

    Args:
        dossiers: 原始的 section_dossiers dict
        facts: extract_section_facts() 返回的 facts dict

    Returns:
        注入 facts 后的 dossiers
    """
    if audit is not None:
        audit.setdefault("schema_version", "facts_extraction_audit.v1")
        audit.setdefault("input_section_count", 0)
        audit.setdefault("extracted_fact_count", 0)
        audit.setdefault("facts_extraction_types", [])
        audit.setdefault("removed_raw_paragraph_count", 0)
        audit.setdefault("removed_raw_key_fact_count", 0)
        audit.setdefault("final_suggested_paragraph_count", 0)
        audit.setdefault("sections", {})

    if not dossiers or not facts:
        return dossiers or {}

    result = dict(dossiers)

    for section_type, section_facts in facts.items():
        if not section_facts:
            continue

        target_sections = _target_dossier_sections(section_type, result)
        if not target_sections:
            continue

        for target_section in target_sections:
            dossier = dict(result[target_section]) if isinstance(result[target_section], dict) else {}
            # 生成基于 facts 的段落建议
            paragraphs = _facts_to_paragraphs(target_section, section_facts)
            if not paragraphs and target_section != section_type:
                paragraphs = _facts_to_paragraphs(section_type, section_facts)
            existing = [str(item).strip() for item in list(dossier.get("suggested_paragraphs", []) or []) if str(item).strip()]
            kept_existing, removed_existing = _filter_raw_pdf_paragraphs(existing)
            if paragraphs:
                dossier["suggested_paragraphs"] = paragraphs + kept_existing
            else:
                dossier["suggested_paragraphs"] = kept_existing
            existing_key_facts = [str(item).strip() for item in list(dossier.get("key_facts", []) or []) if str(item).strip()]
            kept_key_facts, removed_key_facts = _filter_raw_pdf_paragraphs(existing_key_facts)
            dossier["key_facts"] = kept_key_facts
            # 将结构化 facts 作为 key_facts 追加
            for key, value in section_facts.items():
                if isinstance(value, list):
                    dossier["key_facts"].append(f"{key}: {'、'.join(str(v) for v in value[:3])}")
                elif isinstance(value, str):
                    dossier["key_facts"].append(f"{key}: {value}")
                elif isinstance(value, bool):
                    dossier["key_facts"].append(f"{key}: {'是' if value else '否'}")

            metadata = dict(dossier.get("metadata", {}) or {})
            metadata["facts_extraction_applied"] = True
            metadata["facts_extraction_source_section"] = section_type
            metadata["facts_extraction_types"] = sorted(section_facts.keys())
            metadata["removed_raw_paragraph_count"] = len(removed_existing)
            metadata["removed_raw_key_fact_count"] = len(removed_key_facts)
            dossier["metadata"] = metadata

            if audit is not None:
                fact_count = len(section_facts)
                audit["extracted_fact_count"] = int(audit.get("extracted_fact_count", 0) or 0) + fact_count
                audit["removed_raw_paragraph_count"] = int(audit.get("removed_raw_paragraph_count", 0) or 0) + len(removed_existing)
                audit["removed_raw_key_fact_count"] = int(audit.get("removed_raw_key_fact_count", 0) or 0) + len(removed_key_facts)
                audit["facts_extraction_types"] = sorted(
                    set(list(audit.get("facts_extraction_types", []) or []) + [target_section])
                )
                audit["final_suggested_paragraph_count"] = (
                    int(audit.get("final_suggested_paragraph_count", 0) or 0)
                    + len(dossier.get("suggested_paragraphs", []) or [])
                )
                audit.setdefault("sections", {})[target_section] = {
                    "source_section_type": section_type,
                    "fact_count": fact_count,
                    "inserted_fact_paragraph_count": len(paragraphs),
                    "kept_existing_paragraph_count": len(kept_existing),
                    "removed_raw_paragraph_count": len(removed_existing),
                    "removed_raw_key_fact_count": len(removed_key_facts),
                    "final_suggested_paragraph_count": len(dossier.get("suggested_paragraphs", []) or []),
                }

            result[target_section] = dossier

    return result


_SECTION_TO_DOSSIER_ALIASES = {
    "risk_factors": ["risks"],
    "risks": ["risks"],
    "management_discussion": ["financial_analysis", "strategy_business"],
    "mda": ["financial_analysis", "strategy_business"],
    "financial_statements": ["financial_analysis", "three_statement_summary"],
    "business": ["business_overview"],
    "business_overview": ["business_overview"],
    "ownership_governance": ["ownership_governance"],
    "shareholder_structure": ["ownership_governance"],
}


def _target_dossier_sections(section_type: str, dossiers: dict[str, Any]) -> list[str]:
    """Map PDF section keys onto report dossier keys."""
    aliases = _SECTION_TO_DOSSIER_ALIASES.get(str(section_type), [str(section_type)])
    return [alias for alias in aliases if alias in dossiers]


_RAW_PDF_MARKERS = (
    "公司坚持",
    "报告期内主要经营情况",
    "一是",
    "二是",
    "三是",
    "四是",
    "五是",
    "√适用",
    "□不适用",
    "年度报告",
    "管理层讨论与分析",
)


def _filter_raw_pdf_paragraphs(paragraphs: list[str]) -> tuple[list[str], list[str]]:
    """Remove raw annual-report prose from fallback paragraphs."""
    kept: list[str] = []
    removed: list[str] = []
    for paragraph in paragraphs:
        text = str(paragraph or "").strip()
        if not text:
            continue
        if _looks_like_raw_pdf_paste(text):
            removed.append(text)
        else:
            kept.append(text)
    return kept, removed


def _looks_like_raw_pdf_paste(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    marker_count = sum(1 for marker in _RAW_PDF_MARKERS if marker in text or marker in compact)
    if marker_count >= 2:
        return True
    if len(compact) > 180 and marker_count >= 1:
        return True
    if len(compact) > 260 and ("。" in text or "，" in text):
        return True
    return False


def _facts_to_paragraphs(
    section_type: str,
    facts: dict[str, Any],
) -> list[str]:
    """将结构化 facts 转为段落文本。"""
    paragraphs = []

    if section_type == "business_overview":
        parts = []
        if facts.get("products"):
            parts.append(f"主营产品以{'、'.join(facts['products'][:3])}为核心")
        if facts.get("channels"):
            parts.append(f"渠道侧覆盖{'、'.join(facts['channels'][:4])}")
        if facts.get("revenue"):
            parts.append(f"报告期内披露的收入指标为{facts['revenue']}")
        if facts.get("core_competitiveness"):
            parts.append(f"竞争优势主要来自{'、'.join(facts['core_competitiveness'][:5])}")
        if parts:
            paragraphs.append("；".join(parts) + "。这些信息来自官方年报章节摘要，正文只保留归纳后的业务事实。")
            paragraphs.append(
                "业务概览应围绕产品结构、销售渠道、品牌或工艺壁垒以及收入贡献展开，"
                "避免直接复述年报中的长段经营情况。"
            )

    elif section_type == "ownership_governance":
        parts = []
        if facts.get("governance_bodies"):
            parts.append(f"治理结构包含{'、'.join(facts['governance_bodies'][:4])}")
        if facts.get("shareholder_info"):
            parts.append(f"股东信息涉及{'、'.join(facts['shareholder_info'][:3])}")
        if parts:
            paragraphs.append("；".join(parts) + "。")

    elif section_type in {"risk_factors", "risks"}:
        if facts.get("industry_risks"):
            risks = "、".join(facts["industry_risks"][:6])
            paragraphs.append(f"风险评估以官方披露和行业变量为基础，当前识别的主要风险包括：{risks}。")
        if facts.get("has_official_risk_section"):
            paragraphs.append("以上风险基于官方风险提示章节，风险影响主要体现在收入、毛利率、现金流或估值假设的变化上。")
        else:
            paragraphs.append("以上风险基于公开财务数据与行业研究，待官方年报风险提示章节进一步校验。")

    elif section_type in {"management_discussion", "strategy_business"}:
        parts = []
        if facts.get("operations"):
            parts.append(f"经营亮点：{'、'.join(facts['operations'][:4])}")
        if facts.get("strategic_focus"):
            parts.append(f"战略重点：{'、'.join(facts['strategic_focus'][:5])}")
        if parts:
            paragraphs.append("；".join(parts) + "。")

    elif section_type in {"financial_statements", "financial_analysis", "three_statement_summary"}:
        metric_parts = []
        labels = {
            "revenue": "营业收入",
            "net_profit": "净利润",
            "total_assets": "总资产",
            "total_liabilities": "总负债",
            "equity": "股东权益",
            "gross_margin": "毛利率",
            "net_margin": "净利率",
            "operating_cashflow": "经营现金流",
        }
        for key, label in labels.items():
            if facts.get(key):
                metric_parts.append(f"{label}{facts[key]}")
        if metric_parts:
            paragraphs.append(
                "财务分析优先使用结构化三表和官方披露口径，当前可用指标包括"
                + "、".join(metric_parts[:6])
                + "。"
            )
            paragraphs.append(
                "财务分析进一步解释收入规模、利润质量、资产负债结构与现金流之间的关系，"
                "不把三表数字孤立罗列为结论。"
            )
        elif facts.get("has_financial_data"):
            paragraphs.append("已识别官方财务报表章节，后续分析结合结构化三表指标展开收入、利润、资产负债和现金流分析。")

    return paragraphs
