"""PDF / 文本编码自动检测与修复模块。

核心场景
--------
GB2312 (GBK) 编码的中文文本被错误地按 Latin-1 (ISO-8859-1) 解码，
产生类似 ``ę́(600519)Q1 гĸЧ`` 的乱码 (mojibake)。

典型来源
--------
- Tavily / Serper web_search 返回的中文搜索结果（源站 GB2312 但被误解码）
- 新浪财经等 A 股数据源中转时编码丢失
- CNINFO PDF 元数据字段

修复原理
--------
  1. 检测：CJK 字符比例低 + 0x80-0x9F 控制字符比例高 → 判定为 mojibake
  2. 修复：将 Latin-1 乱码文本按 Latin-1 重新编码回原始字节，
     再用正确的 GBK / GB2312 / UTF-8 解码
  3. 验证：修复后 CJK 比例提升 → 确认修复有效

使用示例
--------
    from src.report.fact_extractors.pdf_encoding import auto_repair_mojibake

    text = "ę́(600519)Q1 гĸЧQ1 гĸЧ"
    repaired, stats = auto_repair_mojibake(text)
    # repaired → "茅(600519)Q1 季度Q1 季度"
    # stats["action"] → "repaired"
"""

from __future__ import annotations

import re
from typing import Optional


# ── 字符范围常量 ───────────────────────────────────

# CJK 统一表意文字 (U+4E00–U+9FFF) + 扩展A (U+3400–U+4DBF)
_CJK_RE = re.compile(r"[一-鿿㐀-䶿]")

# Latin-1 控制字符 0x80–0x9F — 正常中文文本几乎不出现，
# 但 GB2312→Latin-1 mojibake 中大量出现
_LATIN1_CONTROL_RANGE = range(0x80, 0xA0)

# 常见的 mojibake 特征字符 — Latin-1 高频字符
_MOJIBAKE_CHARS: set[str] = {
    "À", "Á", "Â", "Ã", "Ä", "Å", "Æ", "Ç",
    "È", "É", "Ê", "Ë", "Ì", "Í", "Î", "Ï",
    "Ð", "Ñ", "Ò", "Ó", "Ô", "Õ", "Ö", "×",
    "Ø", "Ù", "Ú", "Û", "Ü", "Ý", "Þ", "ß",
    "à", "á", "â", "ã", "ä", "å", "æ", "ç",
    "è", "é", "ê", "ë", "ì", "í", "î", "ï",
    "ð", "ñ", "ò", "ó", "ô", "õ", "ö", "÷",
    "ø", "ù", "ú", "û", "ü", "ý", "þ", "ÿ",
    "ı", "Œ", "œ", "Š", "š", "Ÿ",
    "ˆ", "˜", "–", "—", "‘", "’", "‚", "“",
    "”", "„", "†", "‡", "•", "…", "‰",
    "‹", "›", "€",
    # GB2312 mis-decode 高频字符
    "г", "ĸ", "Ч", "ƽ", "Գ", "ɽ", "̨", "˾", "Σ",
    "Ӣ", "Ŵ", "̩", "Զ", "ι", "·", "½",
}

# 中国公司实体模式 — 辅助判定
_CHINESE_ENTITY_RE = re.compile(
    r"\b\d{6}\.(?:SS|SZ|HK)\b"              # 股票代码
    r"|\(\d{6}\)"                             # 括号代码 (600519)
    r"|\([SHsh]\d{6}\)"                       # (sh600519)
)

# 检测默认阈值
_DEFAULT_CJK_THRESHOLD = 0.05        # CJK 比例 ≥ 5% → 正常中文
_DEFAULT_CONTROL_THRESHOLD = 0.02    # 0x80-0x9F ≥ 2% → mojibake
_DEFAULT_MOJI_RATIO_THRESHOLD = 0.15  # mojibake 特征字符阈值


# ── 检测 ─────────────────────────────────────────

def detect_mojibake(
    text: str,
    cjk_threshold: float = _DEFAULT_CJK_THRESHOLD,
    control_threshold: float = _DEFAULT_CONTROL_THRESHOLD,
    moji_ratio_threshold: float = _DEFAULT_MOJI_RATIO_THRESHOLD,
) -> tuple[bool, dict]:
    """检测文本是否为 GB2312→Latin-1 mojibake。

    检测逻辑：
      1. 如果 CJK 字符比例 >= cjk_threshold → 文本已是正常中文，判定为正常
      2. 如果 0x80–0x9F 控制字符比例 >= control_threshold → mojibake
      3. 辅助：mojibake 特征字符比例 + 中国实体模式匹配

    Args:
        text: 输入文本。
        cjk_threshold: CJK 字符比例下限。超过此值判定为"正常中文"。
        control_threshold: 0x80–0x9F 控制字符比例下限。
        moji_ratio_threshold: mojibake 特征字符比例下限（辅助判定用）。

    Returns:
        (is_mojibake: bool, stats: dict)
        stats 包含检测统计信息：
        - cjk_ratio: CJK 字符比例
        - control_ratio: 0x80-0x9F 控制字符比例
        - moji_ratio: mojibake 特征字符比例
        - has_chinese_entity: 是否匹配中国公司实体模式
        - total_chars: 总字符数
        - reason: 判定原因
    """
    if not text or not isinstance(text, str):
        return False, {"reason": "empty_or_not_string"}

    total = len(text)
    if total < 10:
        return False, {"reason": "too_short"}

    cjk_count = len(_CJK_RE.findall(text))
    cjk_ratio = cjk_count / total

    control_count = sum(1 for ch in text if ord(ch) in _LATIN1_CONTROL_RANGE)
    control_ratio = control_count / total

    moji_count = sum(1 for ch in text if ch in _MOJIBAKE_CHARS)
    moji_ratio = moji_count / total

    has_entity = bool(_CHINESE_ENTITY_RE.search(text))

    stats: dict = {
        "cjk_ratio": round(cjk_ratio, 4),
        "control_ratio": round(control_ratio, 4),
        "moji_ratio": round(moji_ratio, 4),
        "has_chinese_entity": has_entity,
        "total_chars": total,
    }

    # 已有足够 CJK → 正常中文
    if cjk_ratio >= cjk_threshold:
        return False, {**stats, "reason": "high_cjk_ratio"}

    # 控制字符比例高 → mojibake
    if control_ratio >= control_threshold:
        return True, {**stats, "reason": "high_control_ratio"}

    # mojibake 特征字符 + 中国实体
    if moji_ratio >= moji_ratio_threshold and has_entity:
        return True, {**stats, "reason": "high_moji_ratio_with_entity"}

    # mojibake 特征字符极高
    if moji_ratio >= moji_ratio_threshold * 2:
        return True, {**stats, "reason": "very_high_moji_ratio"}

    return False, {**stats, "reason": "below_threshold"}


# ── 修复 ─────────────────────────────────────────

def repair_mojibake(text: str) -> str:
    """修复 GB2312 编码被误当做 UTF-8 或 Latin-1 解码的 mojibake。

    调试发现的典型路径：
      GB2312 字节 → 被误当做 UTF-8 解码 → 产生 ``ę́(600519)Q1 гĸЧ``
      修复：乱码字符串按 UTF-8 重新编码回字节 → 用 GBK 解码

    次要路径：
      GB2312 字节 → 被误当做 Latin-1 解码 → 产生 ``Ã¨Ã¹``
      修复：乱码字符串按 Latin-1 编码回字节 → 用 GBK 解码

    Args:
        text: 疑似 mojibake 的文本。

    Returns:
        修复后的文本。若所有策略都失败，返回原文。
    """
    if not text:
        return text

    # ── 策略 1: UTF-8 re-encode → GBK decode ──
    # 适用范围：GB2312 字节被误当做 UTF-8 解码
    # 例如: ę́(600519) → encode('utf-8') → c3a8cca828... → decode('gbk') → 茅台(600519)
    candidates: list[tuple[str, str]] = []

    for encode_as in ["utf-8", "utf-8", "latin-1", "latin-1"]:
        for decode_as in ["gbk", "gb2312", "gb18030"]:
            if encode_as == decode_as:
                continue
            repaired = _try_repair(text, encode_as, decode_as)
            if repaired is not None and repaired != text:
                cjk_count = len(_CJK_RE.findall(repaired))
                if cjk_count > 0:
                    candidates.append((repaired, cjk_count))

    if not candidates:
        return text

    # 选 CJK 字符数最多的修复结果
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[0][0]


def _try_repair(text: str, encode_as: str, decode_as: str) -> Optional[str]:
    """用指定编码路径尝试修复 mojibake。

    流程：text → encode_as 编码 → decode_as 解码

    使用两阶段降级策略：
      1. 先尝试精确解码（strict mode）
      2. 若失败，使用 surrogateescape + replace 容错模式
         - surrogateescape: 将无效字节编码为代理字符保留
         - replace: 剩余无效字节替换为 �

    Args:
        text: 乱码文本
        encode_as: 将 text 按此编码转回字节（当前乱码的"错误"编码）
        decode_as: 将字节按此编码解码（正确的编码）

    Returns:
        修复后的字符串，失败返回 None。
    """
    try:
        raw_bytes = text.encode(encode_as)
    except (UnicodeEncodeError, LookupError):
        return None

    # Phase 1: strict mode
    try:
        return raw_bytes.decode(decode_as)
    except UnicodeDecodeError:
        pass

    # Phase 2: fallback — replace 模式处理少量无效字节
    try:
        return raw_bytes.decode(decode_as, errors="replace")
    except (UnicodeDecodeError, LookupError):
        return None


# ── 自动检测+修复 ─────────────────────────────────

def auto_repair_mojibake(
    text: str,
    cjk_threshold: float = _DEFAULT_CJK_THRESHOLD,
) -> tuple[str, dict]:
    """自动检测并修复 GB2312→Latin-1 mojibake。

    这是最常用的顶层接口。先检测 → 若是 mojibake → 修复 → 验证修复效果。

    Args:
        text: 输入文本。
        cjk_threshold: CJK 比例阈值，传给 detect_mojibake。

    Returns:
        (repaired_text: str, stats: dict)
        - 正常文本 → 返回原文，stats["action"] = "no_mojibake_detected"
        - 乱码 → 返回修复文本，stats["action"] = "repaired"
        - 乱码但修复无改善 → 返回原文，stats["action"] = "repair_no_improvement"
    """
    if not text or not isinstance(text, str):
        return text, {"action": "skipped"}

    is_moji, stats = detect_mojibake(text, cjk_threshold=cjk_threshold)

    if not is_moji:
        return text, {**stats, "action": "no_mojibake_detected"}

    # 尝试修复
    repaired = repair_mojibake(text)

    # 验证修复效果
    orig_cjk = len(_CJK_RE.findall(text))
    new_cjk = len(_CJK_RE.findall(repaired))

    if new_cjk > orig_cjk and new_cjk > 0:
        return repaired, {
            **stats,
            "action": "repaired",
            "orig_cjk_chars": orig_cjk,
            "new_cjk_chars": new_cjk,
        }

    # 修复未提升 CJK → 可能误判，回退原文
    return text, {
        **stats,
        "action": "repair_no_improvement",
        "orig_cjk_chars": orig_cjk,
        "new_cjk_chars": new_cjk,
    }


def batch_auto_repair(
    texts: list[str],
    cjk_threshold: float = _DEFAULT_CJK_THRESHOLD,
) -> list[tuple[str, dict]]:
    """批量自动检测+修复。

    Args:
        texts: 输入文本列表。
        cjk_threshold: CJK 比例阈值。

    Returns:
        每个元素对应 (repaired_text, stats) 的列表。
    """
    return [auto_repair_mojibake(t, cjk_threshold=cjk_threshold) for t in texts]


# ── 兼容接口 ─────────────────────────────────────

def has_mojibake(text: str) -> bool:
    """检测文本是否有 mojibake（兼容现有接口）。

    对应 pdf_rag_pipeline.py 中 _has_mojibake() 的增强版。
    """
    is_moji, _ = detect_mojibake(text)
    return is_moji


def clean_mojibake(text: str) -> str:
    """自动修复 mojibake 并返回纯文本（兼容现有清洗接口）。"""
    repaired, _ = auto_repair_mojibake(text)
    return repaired


# ── Self-test (__main__) ─────────────────────────

if __name__ == "__main__":
    import sys
    # 确保终端能处理 Unicode 输出
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    def _safe(text: str, max_len: int = 80) -> str:
        return text[:max_len].encode("utf-8", errors="backslashreplace").decode("utf-8")

    print("=" * 60)
    print("pdf_encoding.py — 自检测试")
    print("=" * 60)

    # 测试用例: (text, label, expected_action, min_cjk_after)
    test_cases = [
        (
            "ę́(600519)Q1 гĸЧQ1 гĸЧ",
            "mojibake_real_1",
            "repaired",
            1,
        ),
        (
            "ę́(600519)Ię́ ĸЧIę́ ĸЧ",
            "mojibake_real_2",
            "repaired",
            1,
        ),
        (
            "ę́(600519)ֱƽ гĸԳЧֱƽ гĸԳЧ",
            "mojibake_real_3",
            "repaired",
            1,
        ),
        (
            "| 2 | ę́(600519)Q1 гĸЧQ1 гĸЧ\") | ˾ | 2026-05-03 | ֤ȯɷ޹˾ |  |",
            "mojibake_table_row",
            "repaired",
            1,
        ),
        (
            "公司拟以实施权益分派股权登记日登记的总股本扣除回购专用账户中的股份为基数",
            "clean_chinese",
            "no_mojibake_detected",
            20,
        ),
        (
            "Kweichow Moutai Co., Ltd. is a leading liquor company in China.",
            "english",
            "no_mojibake_detected",
            0,
        ),
        (
            "Hello, 世界! 这是混合文本 with mixed content.",
            "mixed",
            "no_mojibake_detected",
            5,
        ),
    ]

    passed = 0
    failed = 0

    for text, label, expected_action, min_cjk in test_cases:
        repaired, stats = auto_repair_mojibake(text)
        action = stats.get("action", "?")
        cjk_after = len(_CJK_RE.findall(repaired))

        ok = action == expected_action and cjk_after >= min_cjk
        status = "✅" if ok else "❌"
        if ok:
            passed += 1
        else:
            failed += 1

        print(f"\n{status} {label}")
        print(f"  原始: {_safe(text)}")
        print(f"  修复: {_safe(repaired)}")
        print(f"  状态: {action} | CJK: {cjk_after} (期望最少 {min_cjk})")
        if action == "repaired":
            print(f"      原始 CJK: {stats.get('orig_cjk_chars')} → 修复后: {stats.get('new_cjk_chars')}")

    print(f"\n{'=' * 60}")
    print(f"结果: {passed} 通过, {failed} 失败 / {len(test_cases)}")
    print(f"{'=' * 60}")

    # 批量测试
    print("\n批量修复:")
    texts = [t for t, _, exp, _ in test_cases[:3]]
    results = batch_auto_repair(texts)
    for i, (original, (repaired, stats)) in enumerate(zip(texts, results)):
        status = "✅" if stats.get("action") == "repaired" else "❌"
        print(f"  {status} [{i}] {_safe(repaired)}")

    # 测试 has_mojibake / clean_mojibake 兼容接口
    assert has_mojibake("ę́(600519)Q1 гĸЧ") is True
    assert has_mojibake("贵州茅台酒股份有限公司") is False
    cleaned = clean_mojibake("ę́(600519)Q1 гĸЧ")
    assert len(_CJK_RE.findall(cleaned)) > 0
    print("\n兼容接口测试: ✅")

    if failed:
        sys.exit(1)
    print("\n全部测试通过 ✅")
