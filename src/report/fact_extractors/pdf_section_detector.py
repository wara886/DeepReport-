"""A 股 / 港股年报段落标题检测与切分模块。

核心场景
--------
CNINFO (巨潮资讯网) 的 A 股年报 PDF 提取后，得到的长文本需要按
"第一节 公司简介和主要财务指标" / "第三节 管理层讨论与分析" 等标题
边界切分为结构化 section，才能喂给下游的 smart chunker。

与 pdf_rag_pipeline.py 的区别
-----------------------------
- pdf_rag_pipeline.py 的 build_section_map() 基于 PDF 页面（page_number + bookmarks）
- pdf_section_detector.py 基于纯文本标题匹配（不依赖 PDF 元数据），
  适用于任何文本来源（Tavily snippet、纯文本 PDF、OCR 结果）

使用示例
--------
    from src.report.fact_extractors.pdf_section_detector import detect_sections

    text = "第一节 公司简介和主要财务指标\n公司名称：贵州茅台...\n第三节 管理层讨论与分析\n2025年收入增长..."
    sections = detect_sections(text, market="cn_a")
    # → {
    #     "business_overview": "公司名称：贵州茅台...",
    #     "management_discussion": "2025年收入增长...",
    #   }
"""

from __future__ import annotations

import re
from typing import Any, Optional


# ── A 股年报"第X节"标准标题 ──────────────────────

# 按"第X节"顺序排列的标准章节（2024/2025 格式）
CN_A_SECTION_ORDER = [
    (r"第[一二三四五六七八九十\d一二三]+节\s*释义", "glossary"),
    (r"第[一二三四五六七八九十\d一二三]+节\s*公司简介和主要财务指标", "business_overview"),
    (r"第[一二三四五六七八九十\d一二三]+节\s*公司(?:业务|简介)(?:和|与)?(?:主要财务指标|概况)?", "business_overview"),
    (r"第[一二三四五六七八九十\d一二三]+节\s*(?:经营情况|管理层)讨论与分析", "management_discussion"),
    (r"第[一二三四五六七八九十\d一二三]+节\s*公司治理", "ownership_governance"),
    (r"第[一二三四五六七八九十\d一二三]+节\s*(?:环境与社会责任|ESG)", "esg"),
    (r"第[一二三四五六七八九十\d一二三]+节\s*重要事项", "important_matters"),
    (r"第[一二三四五六七八九十\d一二三]+节\s*股份变动及股东情况", "shareholder_structure"),
    (r"第[一二三四五六七八九十\d一二三]+节\s*(?:优先股|债券)相关情况", "special_securities"),
    (r"第[一二三四五六七八九十\d一二三]+节\s*财务报告", "financial_statements"),
]

# 无"第X节"前缀的独立标题（部分早期报告或非标格式）
CN_A_FREE_STANDING = [
    (r"释义", "glossary"),
    # 业务概览 — 覆盖各种非标准格式
    (r"公司简介(?:和|与)?主要财务指标", "business_overview"),
    (r"(?:主营业务|业务(?:概览|情况|描述|概要)|公司业务|公司概要|经营概览|主要业务|业务发展)", "business_overview"),
    (r"公司(?:基本)?概况", "business_overview"),
    (r"(?:公司)?简介", "business_overview"),
    (r"管理层讨论与分析|管理层讨论|经营情况讨论与分析|经营讨论与分析", "management_discussion"),
    (r"公司治理", "ownership_governance"),
    (r"(?:环境与社会责任|ESG|可持续发展|环境\s*社会\s*治理)", "esg"),
    (r"重要事项", "important_matters"),
    (r"股份变动及股东情况|股东情况|前十名股东|股东变动", "shareholder_structure"),
    (r"(?:优先股|债券)相关情况", "special_securities"),
    (r"财务报告|审计报告|财务报表", "financial_statements"),
    (r"风险提示|可能面对的风险|风险因素|风险分析", "risk_factors"),
    (r"核心竞争力分析|核心竞争能力", "business_overview"),
    # 中文数字标号前缀（深交所/非标格式使用 "一、公司简介"）
    (r"[一二三四五六七八九十]+[、.．]\s*公司简介", "business_overview"),
    (r"[一二三四五六七八九十]+[、.．]\s*(?:业务概要|经营概览|公司业务)", "business_overview"),
    (r"[一二三四五六七八九十]+[、.．]\s*(?:经营情况|管理层)讨论与分析", "management_discussion"),
    (r"[一二三四五六七八九十]+[、.．]\s*公司治理", "ownership_governance"),
    (r"[一二三四五六七八九十]+[、.．]\s*财务报告", "financial_statements"),
    (r"[一二三四五六七八九十]+[、.．]\s*风险提示", "risk_factors"),
]

# 港股年报常见标题
HK_SECTION_PATTERNS = [
    (r"(?:chairman'?s|ceo'?s)\s+(?:statement|letter|message|report)", "chairman_statement"),
    (r"business\s+(?:overview|review|model|description|and\s+strategy)", "business_overview"),
    (r"(?:management\s+)?discussion\s+and\s+analysis|MD&A|financial\s+review", "management_discussion"),
    (r"corporate\s+governance(?: report)?", "ownership_governance"),
    (r"risk\s+(?:factors|management)", "risk_factors"),
    (r"(?:substantial|principal|major)\s+shareholders", "shareholder_structure"),
    (r"financial\s+(?:statements|position|performance|review)", "financial_statements"),
    (r"(?:notes\s+to\s+the\s+)?financial\s+statements", "financial_statements"),
    (r"environmental,\s*social(?:\s+and\s+governance)?|ESG", "esg"),
    (r"directors'?\s+report|board\s+report", "ownership_governance"),
    (r"independent\s+(?:auditor|audit)", "financial_statements"),
]

# 美股 10-K/10-Q 标准 Item 标题
US_SECTION_PATTERNS = [
    (r"item\s*1[aA]?\.?\s*risk\s+factors", "risk_factors"),
    (r"item\s*1\.?\s*business", "business_overview"),
    (r"item\s*1[bcBC]\.?", "other_qualitative"),
    (r"item\s*2\.?\s*properties", "business_overview"),
    (r"item\s*3\.?\s*legal\s+proceedings", "important_matters"),
    (r"item\s*5\.?\s*market\s+for\s+registrant", "shareholder_structure"),
    (r"item\s*6\.?\s*(?:reserved|selected)", "financial_statements"),
    (r"item\s*7\.?\s*management", "management_discussion"),
    (r"item\s*7[aA]\.?\s*quantitative", "risk_factors"),
    (r"item\s*8\.?\s*financial\s+statements", "financial_statements"),
    (r"item\s*9\.?\s*(?:changes|accounting)", "ownership_governance"),
    (r"item\s*9[aA]\.?\s*controls", "ownership_governance"),
    (r"item\s*10\.?\s*directors", "ownership_governance"),
    (r"item\s*11\.?\s*executive\s+compensation", "ownership_governance"),
    (r"item\s*12\.?\s*security\s+ownership", "shareholder_structure"),
    (r"item\s*13\.?\s*certain\s+relationships", "ownership_governance"),
    (r"item\s*14\.?\s*principal\s+accounting", "ownership_governance"),
    (r"item\s*15\.?\s*exhibits", "financial_statements"),
]

# 加载时的编译缓存
_CN_A_PATTERNS: list[tuple[re.Pattern, str]] = []
_HK_PATTERNS: list[tuple[re.Pattern, str]] = []
_US_PATTERNS: list[tuple[re.Pattern, str]] = []


def _compile() -> None:
    """延迟编译所有正则（在模块首次调用时执行）。"""
    if _CN_A_PATTERNS:
        return
    for pat, key in CN_A_SECTION_ORDER + CN_A_FREE_STANDING:
        _CN_A_PATTERNS.append((re.compile(pat, re.I), key))
    for pat, key in HK_SECTION_PATTERNS:
        _HK_PATTERNS.append((re.compile(pat, re.I), key))
    for pat, key in US_SECTION_PATTERNS:
        _US_PATTERNS.append((re.compile(pat, re.I), key))


# ── 主检测函数 ───────────────────────────────────

def detect_sections(
    text: str,
    market: str = "cn_a",
    include_unmatched: bool = False,
) -> dict[str, str]:
    """检测文本中的 section 标题边界，按标题切分文本。

    算法：
      1. 按行扫描文本（保留原始分段）
      2. 对每行匹配 section 标题模式
      3. 命中标题时，结束上一个 section，开始新 section
      4. 标题内容计入新的 section（不含标题行本身？包含？这里设计为包含标题行本身作为上下文）

    Args:
        text: 年报文本（可以是纯文本、PDF 提取文本、web snippet）
        market: 市场类型 — "cn_a" | "hk" | "us"
        include_unmatched: 是否包括未匹配到任何 section 的文本（作为 "other"）

    Returns:
        dict[str, str]: section_key → 该 section 的文本内容
        按文本中出现顺序排列（Python 3.7+ dict 保持插入顺序）。
    """
    if not text:
        return {}

    _compile()

    patterns = _get_patterns(market)
    if not patterns:
        return {"other": text} if include_unmatched else {}

    lines = text.splitlines()
    sections: list[tuple[str, str]] = []  # (key, accumulated_lines)
    current_key: Optional[str] = None
    current_lines: list[str] = []

    def flush() -> None:
        if current_key is not None and current_lines:
            content = _clean_section_text("\n".join(current_lines))
            if content:
                sections.append((current_key, content))

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current_key is not None:
                current_lines.append(line)
            continue

        # 检查是否匹配标题
        matched_key = _match_heading(stripped, patterns, market)

        if matched_key:
            flush()  # 保存上一个 section
            current_key = matched_key
            current_lines = [line]  # 标题行本身作为新 section 的第一行
        elif current_key is not None:
            current_lines.append(line)
        else:
            # 尚未匹配到任何 section — 如果是 cn_a，先尝试用首行内容推断
            if not current_key and "年度报告" in stripped:
                current_key = "other"
                current_lines = [line]
            else:
                pass  # 静默丢弃前导内容（封面、目录等）

    flush()

    # 合并同一 section_key 的连续段落（如果同一个 key 被匹配多次）
    merged: dict[str, list[str]] = {}
    for key, content in sections:
        merged.setdefault(key, []).append(content)

    result: dict[str, str] = {}
    for key, contents in merged.items():
        combined = "\n\n".join(contents)
        result[key] = combined

    # 未匹配内容
    if include_unmatched and not result:
        result["other"] = _clean_section_text(text)

    return result


def detect_section_boundaries(
    text: str,
    market: str = "cn_a",
) -> list[dict[str, Any]]:
    """检测文本中所有 section 标题边界的位置信息。

    返回列表而非 dict，保留标题在源文本中的位置。
    适用于需要做精确 chunk 定位的场景。

    Returns:
        [{"key": "business_overview", "title": "第二节 公司简介", "start": 120, "end": 350}, ...]
        位置是字符偏移量（char offset）。
    """
    if not text:
        return []

    _compile()
    patterns = _get_patterns(market)
    if not patterns:
        return []

    boundaries: list[dict[str, Any]] = []
    lines = text.splitlines(keepends=True)

    current_offset = 0
    for line in lines:
        stripped = line.strip()
        if stripped:
            matched_key = _match_heading(stripped, patterns, market)
            if matched_key:
                boundaries.append({
                    "key": matched_key,
                    "title": stripped,
                    "offset": current_offset,
                    "line": stripped,
                })
        current_offset += len(line)

    # 补全 end 位置（下一标题的 offset 或文本末尾）
    result = []
    for i, b in enumerate(boundaries):
        end = boundaries[i + 1]["offset"] if i + 1 < len(boundaries) else len(text)
        result.append({
            "key": b["key"],
            "title": b["title"],
            "start": b["offset"],
            "end": end,
            "content": text[b["offset"]:end].strip(),
        })

    return result


def detect_report_type(text: str) -> str:
    """检测文本是哪种类型的报告，返回市场类型。

    基于文本内容特征：CNINFO 年度报告 / HK 年报 / SEC 10-K。

    Returns:
        "cn_a" | "hk" | "us" | "unknown"
    """
    if not text:
        return "unknown"
    sample = text[:2000].lower()

    # CNINFO A 股
    if re.search(r"[第\d一二三]+\s*节\s*(?:公司简介|释义|管理层讨论|财务报告)", sample):
        return "cn_a"
    if re.search(r"(?:年度报告|半年度报告|季度报告)\s*(?:正文|全文)?", sample):
        return "cn_a"
    if re.search(r"(cninfo|巨潮)", sample, re.I):
        return "cn_a"

    # SEC (美股)
    if re.search(r"(united states securities and exchange commission|sec|form\s*10-?[kq])", sample):
        return "us"
    if re.search(r"item\s*\d+[a-z]?\.?\s*(?:business|risk factors|management)", sample):
        return "us"

    # HK
    if re.search(r"(stock code|hong kong exchange|hkex|annual report \d{4})", sample):
        return "hk"
    if re.search(r"(this annual report|the board of directors|principal activities)", sample):
        return "hk"

    return "unknown"


# ── 内部辅助 ────────────────────────────────────

def _get_patterns(market: str) -> list[tuple[re.Pattern, str]]:
    if market == "cn_a":
        return _CN_A_PATTERNS
    elif market == "hk":
        return _HK_PATTERNS
    elif market == "us":
        return _US_PATTERNS
    return []


def _match_heading(line: str, patterns: list[tuple[re.Pattern, str]], market: str) -> Optional[str]:
    """检查一行文本是否匹配 section 标题模式。

    对 cn_a 优先匹配"第X节"模式（更精确），再匹配独立标题。
    """
    if market == "cn_a":
        # 先匹配"第X节"模式
        for pat, key in _CN_A_PATTERNS:
            if pat.match(line):
                return key
        # 再匹配独立标题
        for pat, key in patterns:
            if pat.match(line):
                return key
    else:
        for pat, key in patterns:
            if pat.search(line):
                return key
    return None


def _clean_section_text(text: str) -> str:
    """清洗 section 文本：去除多余空行、前导/后置空白。"""
    lines = text.splitlines()
    cleaned = [line for line in lines if not _is_boilerplate(line)]
    return "\n".join(cleaned).strip()


def _is_boilerplate(line: str) -> bool:
    """判断一行是否为常见的 boilerplate（仅在 section 文本清洗中使用）。"""
    stripped = line.strip()
    if not stripped:
        return False
    # 页码
    if re.match(r"^\s*\d+\s*$", stripped):
        return True
    if re.match(r"^\s*第\s*\d+\s*页\s*共\s*\d+\s*页\s*$", stripped):
        return True
    if re.match(r"^\s*page\s+\d+\s+of\s+\d+\s*$", stripped, re.I):
        return True
    # 目录指针
    if re.match(r"^[\.…]{3,}\s*\d+\s*$", stripped):
        return True
    if re.match(r"^\d+\s*[\.…]{3,}\s*$", stripped):
        return True
    return False


# ── 兼容接口 ─────────────────────────────────────

def split_by_heading(text: str, market: str = "cn_a") -> dict[str, str]:
    """旧接口兼容 — 等价于 detect_sections(text, market, include_unmatched=True)。"""
    return detect_sections(text, market=market, include_unmatched=True)


def get_heading_patterns(market: str = "cn_a") -> list[tuple[str, str]]:
    """获取指定市场的标题模式列表 (pattern, section_key)。"""
    _compile()
    if market == "cn_a":
        return [(pat.pattern, key) for pat, key in _CN_A_PATTERNS]
    elif market == "hk":
        return [(pat.pattern, key) for pat, key in _HK_PATTERNS]
    elif market == "us":
        return [(pat.pattern, key) for pat, key in _US_PATTERNS]
    return []


# ── Self-test ────────────────────────────────────

if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    print("=" * 60)
    print("pdf_section_detector.py — 自检测试")
    print("=" * 60)

    # 测试用例 — A 股年报节选
    test_cn_a = (
        "贵州茅台酒股份有限公司2025年年度报告\n\n"
        "第一节 释义\n"
        "证监会 指 中国证券监督管理委员会\n"
        "上交所 指 上海证券交易所\n\n"
        "第二节 公司简介和主要财务指标\n"
        "公司名称：贵州茅台酒股份有限公司\n"
        "法定代表人：张德芹\n"
        "总资产：约3000亿元\n\n"
        "第三节 管理层讨论与分析\n"
        "2025年公司实现营业总收入1720亿元\n"
        "同比增长15%，净利润860亿元\n\n"
        "第十节 财务报告\n"
        "审计报告\n"
        "资产负债表...\n"
    )

    test_hk = (
        "Alibaba Group Holding Limited\n"
        "Annual Report 2025\n\n"
        "Business Overview\n"
        "We reported revenue of RMB1.2 trillion\n"
        "driven by cloud computing and e-commerce.\n\n"
        "Risk Factors\n"
        "Our business is subject to regulatory changes.\n\n"
        "Financial Statements\n"
        "Consolidated Balance Sheet...\n"
    )

    test_us = (
        "UNITED STATES SECURITIES AND EXCHANGE COMMISSION\n"
        "Form 10-K\n\n"
        "Item 1. Business\n"
        "Microsoft is a technology company.\n\n"
        "Item 1A. Risk Factors\n"
        "Our business faces competition.\n\n"
        "Item 7. Management's Discussion and Analysis\n"
        "Revenue grew 12% to $250 billion.\n"
    )

    passed = 0
    failed = 0

    # Test A 股
    sections = detect_sections(test_cn_a, market="cn_a")
    expected_keys_cn = {"glossary", "business_overview", "management_discussion", "financial_statements"}
    missing = expected_keys_cn - set(sections.keys())
    unexpected = set(sections.keys()) - expected_keys_cn
    if not missing:
        print(f"\n✅ cn_a: 全部 {len(expected_keys_cn)} 个 section 检出")
        passed += 1
    else:
        print(f"\n❌ cn_a: 缺失 {missing}")
        failed += 1
    if unexpected:
        print(f"  额外检出: {unexpected}")

    print(f"  section_keys: {list(sections.keys())}")
    for key, content in sections.items():
        print(f"    {key}: {content[:60]}...")

    # Test HK
    sections = detect_sections(test_hk, market="hk")
    expected_keys_hk = {"business_overview", "risk_factors", "financial_statements"}
    missing = expected_keys_hk - set(sections.keys())
    if not missing:
        print(f"\n✅ hk: 全部 {len(expected_keys_hk)} 个 section 检出")
        passed += 1
    else:
        print(f"\n❌ hk: 缺失 {missing}")
        failed += 1
    print(f"  section_keys: {list(sections.keys())}")

    # Test US
    sections = detect_sections(test_us, market="us")
    expected_keys_us = {"business_overview", "risk_factors", "management_discussion"}
    missing = expected_keys_us - set(sections.keys())
    if not missing:
        print(f"\n✅ us: 全部 {len(expected_keys_us)} 个 section 检出")
        passed += 1
    else:
        print(f"\n❌ us: 缺失 {missing}")
        failed += 1
    print(f"  section_keys: {list(sections.keys())}")

    # Test detect_report_type
    for label, txt in [("cn_a", test_cn_a), ("hk", test_hk), ("us", test_us)]:
        detected = detect_report_type(txt)
        ok = detected == label
        status = "✅" if ok else "❌"
        if ok:
            passed += 1
        else:
            failed += 1
        print(f"\n{status} detect_report_type({label}) = {detected}")

    # Test 边界检测
    boundaries = detect_section_boundaries(test_cn_a, market="cn_a")
    print(f"\n✅ section_boundaries: {len(boundaries)} 个边界")
    for b in boundaries:
        print(f"    {b['key']} @{b['start']}-{b['end']}: \"{b['title']}\"")

    print(f"\n{'=' * 60}")
    print(f"结果: {passed} 通过, {failed} 失败 / {passed + failed}")
    print(f"{'=' * 60}")

    if failed:
        sys.exit(1)
    print("全部测试通过 ✅")
