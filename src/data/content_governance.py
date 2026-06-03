"""Generic content governance policies: market-aware + industry-aware + section-aware.

No company-specific hardcodes.  All policies driven by market, sector,
industry_family, section_type, and source_type metadata.
"""

from __future__ import annotations

import re
from typing import Any

# ── Industry family classification ────────────────────────────────────

def classify_industry_family(sector: str, industry: str, company_name: str = "") -> str:
    """Classify a company into an industry_family based on sector/industry metadata."""
    s = str(sector or "").lower().strip()
    i = str(industry or "").lower().strip()
    n = str(company_name or "").lower().strip()
    combined = f"{s} {i} {n}"

    families: list[tuple[str, list[str]]] = [
        ("auto_ev", ["auto", "automotive", "automobile", "vehicle", "vehicles", "ev", "electric vehicle", "car", "truck", "tesla", "汽车", "新能源车", "电动车", "整车"]),
        ("liquor", ["白酒", "liquor", "distilled", "baijiu", "wine", "spirits", "brewery", "酒"]),
        ("food_beverage", ["食品", "饮料", "food", "beverage", "乳业", "dairy", "snack", "调味品", "啤酒"]),
        ("consumer_staples", ["consumer staples", "必需消费", "household", "personal care", "tobacco"]),
        ("semiconductors", ["semiconductor", "半导体", "chip", "foundry"]),
        ("technology", ["technology", "tech", "software", "hardware", "it services"]),
        ("cloud_internet", ["cloud", "internet", "platform", "互联网", "云计算", "ecommerce", "电商", "social media"]),
        ("financials", ["financial", "bank", "insurance", "银行", "保险", "证券", "capital markets", "金融"]),
        ("healthcare", ["healthcare", "pharma", "biotech", "medical", "医药", "生物", "医疗", "制药"]),
        ("industrials", ["industrial", "manufacturing", "工业", "制造", "construction", "transport"]),
        ("energy", ["energy", "oil", "gas", "能源", "石油", "天然气", "coal", "power"]),
        ("materials", ["materials", "chemical", "metal", "材料", "化工", "金属", "mining"]),
        ("real_estate", ["real estate", "房地产", "property", "reit"]),
    ]

    for family, keywords in families:
        if any(kw in combined for kw in keywords):
            return family

    return "generic"


# ── Industry-aware risk terms ─────────────────────────────────────────

INDUSTRY_RISK_TEMPLATES: dict[str, dict[str, Any]] = {
    "liquor": {
        "allowed_terms": [
            "消费需求波动", "价格体系", "渠道库存", "食品安全",
            "品牌声誉", "政策监管", "经销商管理", "宏观消费环境",
            "居民消费意愿", "产品结构升级", "次高端化", "渠道下沉",
        ],
        "banned_terms": [
            "云厂商", "云服务", "GPU", "半导体", "算力", "芯片",
            "互联网流量", "广告收入", "云计算采购", "服务器",
        ],
        "fallback": (
            "白酒行业主要风险包括：消费需求波动、价格体系与渠道库存管理、"
            "食品安全与质量控制、品牌声誉维护、政策监管变化、经销商管理、"
            "宏观消费环境与居民消费意愿。以上风险基于公开财务数据与行业研究，"
            "待官方年报风险提示章节进一步校验。"
        ),
    },
    "food_beverage": {
        "allowed_terms": [
            "消费需求", "原材料价格", "渠道变革", "食品安全",
            "品牌竞争", "渠道库存", "经销商管理", "消费升级",
        ],
        "banned_terms": [
            "云厂商", "GPU", "半导体", "算力", "芯片", "互联网平台",
        ],
        "fallback": (
            "食品饮料行业主要风险包括：原材料价格波动、消费需求变化、"
            "渠道库存管理、食品安全与质量控制、品牌竞争加剧、"
            "政策法规变化。以上风险待官方年报进一步校验。"
        ),
    },
    "consumer_staples": {
        "allowed_terms": [
            "消费需求", "原材料成本", "渠道", "品牌", "零售环境",
        ],
        "banned_terms": ["云厂商", "GPU", "半导体", "算力"],
        "fallback": "消费品行业面临消费需求变化、原材料成本波动和渠道竞争风险，待官方年报进一步校验。",
    },
    "technology": {
        "allowed_terms": [
            "技术迭代", "研发投入", "产品周期", "人才竞争", "供应链",
            "地缘政治", "出口管制", "数据安全", "平台监管",
        ],
        "banned_terms": [],
        "fallback": "科技行业面临技术迭代、研发投入、供应链和监管风险，待官方年报进一步校验。",
    },
    "semiconductors": {
        "allowed_terms": [
            "技术迭代", "资本开支", "产能周期", "供应链", "地缘政治",
            "出口管制", "客户集中度", "研发投入",
        ],
        "banned_terms": ["消费需求波动", "渠道库存", "食品安全"],
        "fallback": "半导体行业面临技术迭代、产能周期、供应链和地缘政治风险，待官方年报进一步校验。",
    },
    "auto_ev": {
        "allowed_terms": [
            "电动车需求", "价格竞争", "交付量", "产能爬坡", "电池成本",
            "自动驾驶监管", "供应链", "召回", "能源业务", "宏观利率",
        ],
        "banned_terms": ["云厂商", "云计算采购", "食品安全", "渠道库存", "白酒"],
        "fallback": (
            "汽车与电动车行业主要风险包括：需求波动与价格竞争、交付和产能爬坡、"
            "电池与供应链成本、自动驾驶和车辆安全监管、召回与质量控制、能源业务执行风险。"
            "以上风险待官方 10-K/10-Q 风险章节进一步校验。"
        ),
    },
    "cloud_internet": {
        "allowed_terms": [
            "云厂商采购", "算力投入", "数据安全", "平台监管", "互联网流量",
            "广告收入", "用户增长", "内容成本",
        ],
        "banned_terms": ["食品安全", "渠道库存", "经销商管理"],
        "fallback": "互联网/云计算行业面临平台监管、数据安全、算力投入和市场竞争风险，待官方年报进一步校验。",
    },
    "financials": {
        "allowed_terms": [
            "息差", "资产质量", "不良率", "资本充足率", "监管政策",
            "信用风险", "市场风险", "流动性风险",
        ],
        "banned_terms": ["消费需求", "渠道库存", "食品安全", "GPU"],
        "fallback": "金融行业面临信用风险、市场风险、流动性风险和监管政策变化，待官方年报进一步校验。",
    },
    "healthcare": {
        "allowed_terms": [
            "研发风险", "临床试验", "审批监管", "专利到期", "集采降价",
            "医保政策", "产品质量",
        ],
        "banned_terms": ["白酒", "渠道库存"],
        "fallback": "医药行业面临研发风险、审批监管、集采政策和专利到期风险，待官方年报进一步校验。",
    },
    "generic": {
        "allowed_terms": [],
        "banned_terms": [],
        "fallback": "基于公开财务数据的经营与估值风险。待官方年报风险提示章节进一步校验后补充行业专项风险分析。",
    },
}


def get_industry_risk_fallback(industry_family: str) -> str:
    """Get the risk fallback template for an industry family."""
    tmpl = INDUSTRY_RISK_TEMPLATES.get(industry_family, INDUSTRY_RISK_TEMPLATES["generic"])
    return str(tmpl.get("fallback", INDUSTRY_RISK_TEMPLATES["generic"]["fallback"]))


def get_industry_banned_risk_terms(industry_family: str) -> list[str]:
    """Get banned risk terms for an industry family."""
    tmpl = INDUSTRY_RISK_TEMPLATES.get(industry_family, INDUSTRY_RISK_TEMPLATES["generic"])
    return list(tmpl.get("banned_terms", []))


# ── Citation binding policy ───────────────────────────────────────────

QUALITATIVE_SECTIONS = {
    "business_overview", "strategy_business", "ownership_governance",
    "shareholder_structure", "risk_factors", "risks",
}

FINANCIAL_SECTIONS = {
    "three_statement_summary", "financial_analysis",
}

VALUATION_SECTIONS = {
    "valuation", "valuation_sensitivity",
}

QUALITATIVE_SOURCE_TYPES = {
    "annual_report_pdf_section_summary", "annual_report_pdf_chunk",
    "official_filing", "exchange_announcement", "company_ir",
    "sec_filing", "hkex_announcement", "cninfo_announcement",
    "official_annual_report", "official_10k", "official_10q",
}

FINANCIAL_TABLE_SOURCE_TYPES = {
    "income_statement", "balance_sheet", "cashflow_statement",
    "income table", "balance table", "cashflow table",
}

MARKET_DATA_TYPES = {
    "market_data", "market_api", "third_party_structured",
    "yahoo_financials", "yahoo_profile", "eastmoney_financials",
}

OFFICIAL_SOURCES = {
    "official_filing", "official_annual_report", "exchange_announcement",
    "company_ir", "sec_edgar", "official_10k", "official_10q",
    "hkex_announcement", "cninfo_announcement",
}


def check_citation_binding(section_type: str, source_type: str) -> str:
    """Check if a citation source_type is appropriate for a section_type.

    Returns "" if OK, or a blocker code string if violated.
    """
    st = str(section_type or "").lower().strip()
    so = str(source_type or "").lower().strip()

    # Qualitative sections must not primarily cite financial tables
    if st in QUALITATIVE_SECTIONS and so in FINANCIAL_TABLE_SOURCE_TYPES:
        return f"citation_mismatch:{st}_citing_{so}"

    # Financial sections must not cite qualitative-only sources for core claims
    # (允许但标记)

    # Governance/risk sections must not cite market data as primary
    if st in {"ownership_governance", "shareholder_structure", "risk_factors"} and so in MARKET_DATA_TYPES:
        return f"citation_mismatch:{st}_citing_market_data"

    # Cash flow should not cite MDA chunks
    if st == "financial_analysis" and so in {"mda", "management_discussion"}:
        return f"citation_mismatch:cashflow_citing_mda"

    return ""


# ── PDF boilerplate patterns (generic, not company-specific) ──────────

PDF_BOILERPLATE_PATTERNS = [
    r'[√✔■☑]\s*适用\s*[□✗✘]\s*不适用',
    r'[□✗✘]\s*适用\s*[√✔■☑]\s*不适用',
    r'报告期内核心竞争力分析',
    r'公司代码\s*[：:]\s*\d+',
    r'股票简称\s*[：:]\s*',
    r'年度报告\s*(?:第\s*)?\d+\s*/\s*\d+',
    r'第\s*\d+\s*页\s*共\s*\d+\s*页',
]


def strip_pdf_boilerplate(text: str) -> str:
    """Remove generic PDF formatting boilerplate."""
    for pat in PDF_BOILERPLATE_PATTERNS:
        text = re.sub(pat, '', text)
    return text


# ── Period resolver ───────────────────────────────────────────────────

def resolve_period_metadata(
    financial_metrics: dict[str, Any] | None = None,
    tables: list[dict[str, Any]] | None = None,
    target_period: str = "",
) -> dict[str, str]:
    """Resolve period metadata from available data.

    Returns: {"latest_available_period": str, "period_mismatch": bool}
    """
    periods: set[str] = set()
    fm = financial_metrics or {}
    if isinstance(fm, dict):
        for v in fm.values():
            p = str(v.get("period", "")) if isinstance(v, dict) else ""
            if re.match(r"(?:FY)?20\d{2}(?:Q[1-4])?", p.upper()):
                periods.add(p.upper())
    for t in (tables or []):
        if isinstance(t, dict):
            for row in (t.get("rows", []) if isinstance(t.get("rows"), list) else []):
                p = str(row.get("period", "")) if isinstance(row, dict) else ""
                if re.match(r"(?:FY)?20\d{2}(?:Q[1-4])?", p.upper()):
                    periods.add(p.upper())

    if not periods:
        return {"latest_available_period": "", "period_mismatch": "unknown"}

    latest = sorted(periods, reverse=True)[0]
    target = str(target_period or "").strip().upper()
    mismatch = target and latest and target != latest
    return {
        "latest_available_period": latest,
        "period_mismatch": "true" if mismatch else "false",
    }


def format_period_metadata_text(metadata: dict[str, str]) -> str:
    """Format period metadata into a display string."""
    latest = metadata.get("latest_available_period", "")
    mismatch = metadata.get("period_mismatch", "unknown")
    if not latest:
        return "最新可得披露数据期：待识别"
    if mismatch == "true":
        return f"最新可得披露数据期：{latest}（与目标期不一致）"
    return f"最新可得披露数据期：{latest}"
