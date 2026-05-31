"""Data-driven company alias resolution for FinSight.

Resolves Chinese/English company names, short names, and tickers to canonical
symbol + company_name + market.  No per-company hardcoded branches in callers.

Usage:
    from src.app.company_aliases import resolve_company_alias, COMPANY_ALIASES

    result = resolve_company_alias("英伟达")
    # -> {"symbol": "NVDA", "company_name": "NVIDIA Corporation", "market": "US",
    #     "matched_alias": "英伟达", "confidence": 0.95}

    result = resolve_company_alias("生成24年英伟达")
    # same result — the text is scanned for all known aliases
"""

from __future__ import annotations

import re
from typing import Any

# ── Data: canonical company entries ──────────────────────────────────────
# Each entry: canonical_symbol, company_name, market, aliases (list)
# Aliases are matched case-insensitively, longest-match-first.
RAW_COMPANY_ENTRIES: list[dict[str, Any]] = [
    # ── US ──────────────────────────────────────────────────────────────
    {
        "symbol": "NVDA",
        "company_name": "NVIDIA Corporation",
        "market": "US",
        "aliases": ["英伟达", "nvidia", "nvda", "NVIDIA"],
    },
    {
        "symbol": "MU",
        "company_name": "Micron Technology, Inc.",
        "market": "US",
        "aliases": ["镁光", "美光", "micron", "micron technology", "mu"],
    },
    {
        "symbol": "TSM",
        "company_name": "Taiwan Semiconductor Manufacturing Company Limited",
        "market": "US",
        "aliases": ["台积电", "台湾积体电路", "台灣積體電路", "tsmc", "taiwan semiconductor", "tsm"],
    },
    {
        "symbol": "LLY",
        "company_name": "Eli Lilly and Company",
        "market": "US",
        "aliases": ["礼来", "礼来公司", "eli lilly", "lilly", "lly"],
    },
    {
        "symbol": "PDD",
        "company_name": "PDD Holdings Inc.",
        "market": "US",
        "aliases": ["拼多多", "pinduoduo", "pdd holdings", "pdd"],
    },
    {
        "symbol": "AAPL",
        "company_name": "Apple Inc.",
        "market": "US",
        "aliases": ["苹果", "apple", "aapl", "Apple"],
    },
    {
        "symbol": "TSLA",
        "company_name": "Tesla, Inc.",
        "market": "US",
        "aliases": ["特斯拉", "tesla", "tsla", "Tesla"],
    },
    {
        "symbol": "AMD",
        "company_name": "Advanced Micro Devices, Inc.",
        "market": "US",
        "aliases": ["超威", "超威半导体", "amd", "Advanced Micro Devices"],
    },
    {
        "symbol": "GOOGL",
        "company_name": "Alphabet Inc.",
        "market": "US",
        "aliases": ["谷歌", "alphabet", "google", "googl", "goog"],
    },
    {
        "symbol": "MSFT",
        "company_name": "Microsoft Corporation",
        "market": "US",
        "aliases": ["微软", "microsoft", "msft"],
    },
    {
        "symbol": "AMZN",
        "company_name": "Amazon.com, Inc.",
        "market": "US",
        "aliases": ["亚马逊", "amazon", "amzn"],
    },
    {
        "symbol": "META",
        "company_name": "Meta Platforms, Inc.",
        "market": "US",
        "aliases": ["meta", "facebook", "fb"],
    },
    {
        "symbol": "INTC",
        "company_name": "Intel Corporation",
        "market": "US",
        "aliases": ["英特尔", "intel", "intc"],
    },
    # ── HK ──────────────────────────────────────────────────────────────
    {
        "symbol": "0700.HK",
        "company_name": "Tencent Holdings Limited",
        "market": "HK",
        "aliases": ["腾讯", "腾讯控股", "tencent", "0700", "0700.hk"],
    },
    {
        "symbol": "9988.HK",
        "company_name": "Alibaba Group Holding Limited",
        "market": "HK",
        "aliases": ["阿里", "阿里巴巴", "alibaba", "9988", "9988.hk"],
    },
    {
        "symbol": "3690.HK",
        "company_name": "Meituan",
        "market": "HK",
        "aliases": ["美团", "meituan", "3690", "3690.hk"],
    },
    {
        "symbol": "9618.HK",
        "company_name": "JD.com, Inc.",
        "market": "HK",
        "aliases": ["京东", "jd.com", "jd", "9618", "9618.hk"],
    },
    {
        "symbol": "1810.HK",
        "company_name": "Xiaomi Corporation",
        "market": "HK",
        "aliases": ["小米", "xiaomi", "1810", "1810.hk"],
    },
    # ── A-Share ─────────────────────────────────────────────────────────
    {
        "symbol": "600519.SS",
        "company_name": "贵州茅台酒股份有限公司",
        "market": "CN",
        "aliases": ["贵州茅台", "茅台", "600519", "600519.ss"],
    },
    {
        "symbol": "300750.SZ",
        "company_name": "宁德时代新能源科技股份有限公司",
        "market": "CN",
        "aliases": ["宁德时代", "宁德", "300750", "300750.sz"],
    },
    {
        "symbol": "002594.SZ",
        "company_name": "比亚迪股份有限公司",
        "market": "CN",
        "aliases": ["比亚迪", "002594", "002594.sz"],
    },
    {
        "symbol": "600036.SS",
        "company_name": "招商银行股份有限公司",
        "market": "CN",
        "aliases": ["招商银行", "招行", "600036", "600036.ss"],
    },
    {
        "symbol": "000858.SZ",
        "company_name": "宜宾五粮液股份有限公司",
        "market": "CN",
        "aliases": ["五粮液", "000858", "000858.sz"],
    },
]

# ── Noise tokens that should NEVER be resolved as company tickers ────────
NOISE_TOKENS: set[str] = {
    "HTML", "PDF", "CSV", "JSON", "TXT", "XML", "API", "URL", "FILE",
    "PATH", "COPY", "打开", "下载",
}


def _contains_cjk(s: str) -> bool:
    """Return True if *s* contains any CJK Unified Ideograph."""
    return any(0x4E00 <= ord(c) <= 0x9FFF for c in s)


def _build_lookup_table() -> list[dict[str, Any]]:
    """Build sorted lookup table: longest alias first to avoid partial matches."""
    entries: list[dict[str, Any]] = []
    for e in RAW_COMPANY_ENTRIES:
        for alias in e["aliases"]:
            entries.append({
                "alias": alias.strip().lower(),
                "symbol": e["symbol"],
                "company_name": e["company_name"],
                "market": e["market"],
                "alias_len": len(alias.strip()),
                "is_cjk": _contains_cjk(alias),
            })
    entries.sort(key=lambda x: x["alias_len"], reverse=True)
    return entries


# Pre-built at import time
_LOOKUP_TABLE: list[dict[str, Any]] = _build_lookup_table()


def resolve_company_alias(text: str) -> dict[str, Any] | None:
    """Scan *text* for known company aliases and return canonical info.

    Returns None if no alias matched.  Matches longest alias first to avoid
    "amd" matching inside "amazon" etc.
    """
    lowered = str(text or "").lower()
    for entry in _LOOKUP_TABLE:
        alias = entry["alias"]
        is_cjk = entry.get("is_cjk", False)
        if is_cjk:
            # CJK aliases: simple substring match (Chinese text has no word boundaries)
            if alias in lowered:
                found = True
            else:
                found = False
        else:
            # Latin aliases: require word boundaries to avoid "amd" in "amazon"
            pattern = r"(?<![a-zA-Z0-9])" + re.escape(alias) + r"(?![a-zA-Z0-9])"
            found = bool(re.search(pattern, lowered))
        if found:
            symbol = entry["symbol"]
            if symbol.upper() in NOISE_TOKENS:
                continue
            return {
                "symbol": entry["symbol"],
                "company_name": entry["company_name"],
                "market": entry["market"],
                "matched_alias": alias,
                "confidence": 0.95,
            }
    return None


def resolve_company_alias_all(text: str) -> list[dict[str, Any]]:
    """Return ALL matching company aliases (for conflict detection)."""
    lowered = str(text or "").lower()
    results: list[dict[str, Any]] = []
    seen_symbols: set[str] = set()
    for entry in _LOOKUP_TABLE:
        alias = entry["alias"]
        is_cjk = entry.get("is_cjk", False)
        if is_cjk:
            found = alias in lowered
        else:
            pattern = r"(?<![a-zA-Z0-9])" + re.escape(alias) + r"(?![a-zA-Z0-9])"
            found = bool(re.search(pattern, lowered))
        if found:
            sym = entry["symbol"]
            if sym.upper() in NOISE_TOKENS or sym in seen_symbols:
                continue
            seen_symbols.add(sym)
            results.append({
                "symbol": entry["symbol"],
                "company_name": entry["company_name"],
                "market": entry["market"],
                "matched_alias": alias,
                "confidence": 0.95,
            })
    return results


def normalize_period(text: str) -> dict[str, Any]:
    """Normalize Chinese/English period expressions to canonical form.

    Returns: {"period": str, "period_kind": str, "confidence": float}
    period_kind is one of: "fiscal_year", "quarter", "latest", "unknown"
    """
    t = str(text or "").strip()

    # "最新" / "latest" → latest
    if re.search(r"(?i)(?:最新|最近|latest|most\s+recent|current)", t):
        return {"period": "latest", "period_kind": "latest", "confidence": 0.90}

    # FY2025, FY 2025
    m = re.search(r"(?i)\bFY\s*[-_]?\s*(20\d{2})\b", t)
    if m:
        return {"period": f"FY{m.group(1)}", "period_kind": "fiscal_year", "confidence": 0.95}

    # 2025Q1, 2025 Q1, 2025-Q1, 2025年Q1, 2025年一季度, 2025第一季度
    m = re.search(r"(20\d{2}|\d{2})\s*年?\s*(?:[Qq]|季)\s*([1-4])\b", t)
    if m:
        y = _norm_year(m.group(1))
        return {"period": f"{y}Q{m.group(2)}", "period_kind": "quarter", "confidence": 0.95}

    # "一季度"/"二季度"/"三"/"四" with year context
    for qn, qp in [("一", "1"), ("二", "2"), ("三", "3"), ("四", "4")]:
        if re.search(rf"第?\s*{qn}\s*季度", t):
            ym = re.search(r"(20\d{2}|\d{2})\s*年?", t)
            if ym:
                y = _norm_year(ym.group(1))
                return {"period": f"{y}Q{qp}", "period_kind": "quarter", "confidence": 0.88}

    # "24年" / "2024年" / "2025年" / "2025全年" / "2025财年" / "2025年度" / "2025年报" / "2025财报"
    # In report generation context, bare "XXXX年" defaults to fiscal_year
    annual_cn = r"(?:年|财年|全年|年度|年报|财报)"
    m = re.search(rf"(?<!\d)(20\d{{2}}|\d{{2}})\s*{annual_cn}", t)
    if m:
        y = _norm_year(m.group(1))
        return {"period": f"FY{y}", "period_kind": "fiscal_year", "confidence": 0.92}

    # "2025" with report context terms
    if re.search(r"(?i)\b(?:annual|full.year|fiscal)\b", t):
        m = re.search(r"(?<!\d)(20\d{2})(?!\d)", t)
        if m:
            return {"period": f"FY{m.group(1)}", "period_kind": "fiscal_year", "confidence": 0.90}

    return {"period": "", "period_kind": "unknown", "confidence": 0.0}


def _norm_year(raw: str) -> int:
    y = int(raw)
    if y < 100:
        return 2000 + y
    return y


def parse_report_request(text: str) -> dict[str, Any]:
    """Parse a user message into report request fields.

    Deterministic parser — no LLM call.  Returns parsed fields
    that should be used before falling back to LLM parsing.

    Returns:
        {
            "intent": str,           # "generate_report" | "artifact_action" | "unknown"
            "symbol": str,           # canonical symbol or ""
            "company_name": str,
            "market": str,
            "period": str,
            "period_kind": str,
            "confidence": float,
            "needs_confirmation": bool,
            "matched_alias": str,
            "source": "deterministic",
        }
    """
    result: dict[str, Any] = {
        "intent": "unknown",
        "symbol": "",
        "company_name": "",
        "market": "",
        "period": "",
        "period_kind": "unknown",
        "confidence": 0.0,
        "needs_confirmation": True,
        "matched_alias": "",
        "source": "deterministic",
    }

    t = str(text or "")

    # ── Detect artifact actions first (before company parsing) ──────────
    artifact_signals = [
        (("打开", "open", "查看", "view"), ("HTML", "html", "报告", "report")),
        (("下载", "download"), ("HTML", "html", "PDF", "pdf", "报告", "report")),
        (("复制", "copy"), ("file", "路径", "path", "链接", "link")),
    ]
    for action_words, target_words in artifact_signals:
        has_action = any(w in t for w in action_words) or any(w in t.lower() for w in action_words)
        has_target = any(w in t for w in target_words) or any(w in t.lower() for w in target_words)
        if has_action and has_target:
            result["intent"] = "artifact_action"
            result["confidence"] = 0.85
            result["source"] = "deterministic"
            return result

    # ── Detect generate_report intent ───────────────────────────────────
    # Chinese generation verbs (substring match — no \b for CJK)
    gen_cn = ("生成", "做一份", "出一份", "创建", "制作", "写", "财报", "研报", "年报", "季报", "报告")
    gen_en = ("generate", "create", "make", "run", "financial report", "company report", "annual report")
    is_gen = any(g in t for g in gen_cn) or any(g in t.lower() for g in gen_en)
    if is_gen:
        result["intent"] = "generate_report"

    # ── Resolve company alias ───────────────────────────────────────────
    alias_result = resolve_company_alias(t)
    if alias_result:
        result["symbol"] = alias_result["symbol"]
        result["company_name"] = alias_result["company_name"]
        result["market"] = alias_result["market"]
        result["matched_alias"] = alias_result["matched_alias"]
        result["confidence"] = max(result["confidence"], alias_result["confidence"])

    # ── Check for multiple company conflicts ────────────────────────────
    all_matches = resolve_company_alias_all(t)
    if len(all_matches) > 1:
        result["needs_confirmation"] = True
        result["missing_fields"] = result.get("missing_fields", []) + ["ambiguous_company"]

    # ── Normalize period ────────────────────────────────────────────────
    period_result = normalize_period(t)
    if period_result["period"]:
        result["period"] = period_result["period"]
        result["period_kind"] = period_result["period_kind"]
        result["confidence"] = max(result["confidence"], period_result["confidence"])

    # ── Confidence gate ─────────────────────────────────────────────────
    has_symbol = bool(result["symbol"])
    has_period = bool(result["period"])
    if is_gen and has_symbol and has_period:
        result["confidence"] = max(result["confidence"], 0.88)
        result["needs_confirmation"] = True  # user mode always confirms
    elif is_gen and has_symbol and not has_period:
        result["confidence"] = max(result["confidence"], 0.65)
    elif is_gen and not has_symbol:
        result["confidence"] = max(result["confidence"], 0.30)

    return result
