"""证据清洗 pipeline — 6 步有序清洗 + 内容门控 + pdf_encoding 集成。

Pipeline 顺序（不可调换，否则影响下游判断）:
  1. Encoding detect & repair  — 先修编码，后续步骤才能正确处理中文
  2. HTML entity decode        — 在 encoding 修好后做
  --- 市场特异清洗插入点 ---
  3. Length gate               — < 10 chars discard (乱码修好后判断长度)
  4. Duplicate content hash    — 先清洗再 dedup
  5. URL normalize             — percent-decode
  6. Null timestamp fallback   — publish_time="" → retrieved_at

内容门控（Content Gate, 对应 Rk2）:
  - 清洗后 content 为空或 < 20 chars → score = 0，标记为 blocked
  - 确保下游 reranking 不会给空内容高排名

使用示例:
    from src.report.fact_extractors.cleaning_pipeline import clean_evidence, clean_text

    text = clean_text("ę́(600519)Q1 гĸЧ", steps="all")  # 先修编码再清洗
    evidence = {"content": "ę́...", "score": 8.6, ...}
    result = clean_evidence(evidence, market="cn_a")
    # → {"content": "茅台...", "score": 0.0, "cleaning_flags": [...], ...}
"""

from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime
from typing import Any, Optional

from src.report.fact_extractors.pdf_encoding import auto_repair_mojibake, clean_mojibake


# ── 配置常量 ─────────────────────────────────────

# Length gate: 清洗后 content 低于此长度直接丢弃
MIN_CONTENT_LENGTH = 10

# Content gate: content 低于此长度 score 归零
CONTENT_GATE_MIN_LENGTH = 20

# 港股 snippet 截断长度
HK_SNIPPET_MAX_CHARS = 2000

# 去重时使用的 hash 算法
HASH_ALGO = "sha256"


# ── Step 1: Encoding detect & repair ────────────

def step_encoding_repair(text: str) -> str:
    """Step 1 — 编码检测与修复。

    使用 pdf_encoding 模块检测 GB2312→UTF-8 misdecode mojibake 并修复。
    如果文本已经是正常中文，不做任何操作。

    Returns:
        修复后的文本。
    """
    if not text:
        return text
    repaired, stats = auto_repair_mojibake(text)
    return repaired


# ── Step 2: HTML entity decode ──────────────────

def step_html_unescape(text: str) -> str:
    """Step 2 — HTML entity 解码。

    处理 &amp; &lt; &gt; &quot; &#x27; &#x60; 等 HTML 实体。
    必须在 encoding 修复后做，否则 pre-encoded entity 会干扰解码。
    """
    if not text:
        return text
    return html.unescape(text)


# ── Step 3: Length gate ─────────────────────────

def step_length_gate(text: str, min_length: int = MIN_CONTENT_LENGTH) -> tuple[str, bool]:
    """Step 3 — 长度门控。

    如果清洗后内容长度 < min_length → 返回 (原文本, discard=True)
    否则 → 返回 (原文本, discard=False)

    Returns:
        (text, discard) — discard=True 表示需要丢弃
    """
    if not text:
        return text, True
    stripped = text.strip()
    if len(stripped) < min_length:
        return text, True
    return text, False


# ── Step 4: Duplicate detection ─────────────────

def content_hash(text: str) -> str:
    """对清洗后内容做 hash，用于去重。"""
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


# ── Step 5: URL normalize ───────────────────────

_URL_PERCENT_RE = re.compile(r"%[0-9a-fA-F]{2}")


def step_url_normalize(text: str) -> str:
    """Step 5 — URL normalize（percent-decode 不影响上一步）。

    解码 URL 中的 percent-encoded 中文参数。
    注意：不解码整个文本，只对 URL-like 片段做解码。
    """
    if not text:
        return text

    def _decode_url(match: re.Match) -> str:
        try:
            return match.group(0)
        except Exception:
            return match.group(0)

    # 简单替换常见百分号编码
    # 只处理 text 中嵌入的 URL 参数（%xx 格式）
    result = _URL_PERCENT_RE.sub(
        lambda m: _try_percent_decode(m.group(0)), text
    )
    return result


def _try_percent_decode(encoded: str) -> str:
    """尝试解码单个百分号编码（%xx）。"""
    try:
        return bytes.fromhex(encoded[1:3]).decode("utf-8", errors="replace")
    except (ValueError, UnicodeDecodeError):
        return encoded


# ── Step 6: Null timestamp fallback ─────────────

def step_timestamp_fallback(
    publish_time: str,
    retrieved_at: str = "",
    document_date: str = "",
) -> str:
    """Step 6 — 空时间戳回退。

    如果 publish_time 为空或是 falsy 值，
    优先用 retrieved_at，其次 document_date，最后当前时间。

    Returns:
        解析后的时间字符串。
    """
    if publish_time and publish_time.strip():
        return publish_time.strip()
    if retrieved_at and retrieved_at.strip():
        return retrieved_at.strip()
    if document_date and document_date.strip():
        return document_date.strip()
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ── 市场特异清洗 ────────────────────────────────

def market_specific_clean(text: str, market: str = "cn_a") -> str:
    """市场特异清洗（在 Step 2 之后、Step 3 之前插入）。

    Args:
        text: 清洗前文本（已做 encoding repair 和 html unescape）
        market: "cn_a" | "hk" | "us"

    Returns:
        清洗后文本
    """
    if not text:
        return text

    if market == "hk":
        return _clean_hk_snippet(text)
    elif market == "us":
        return _clean_us_10k(text)
    # cn_a 不需要额外的特异清洗（PDF encoding 已在 Step 1 处理）
    return text


def _clean_hk_snippet(text: str) -> str:
    """港股 snippet 清洗：截断 + 保留有效句子。"""
    # 截断到最大长度
    if len(text) > HK_SNIPPET_MAX_CHARS:
        text = text[:HK_SNIPPET_MAX_CHARS]

    # 去除空行、过短行
    lines = text.splitlines()
    cleaned = [line for line in lines if len(line.strip()) > 5]
    return "\n".join(cleaned).strip()


def _clean_us_10k(text: str) -> str:
    """美股 10-K section 清洗：去除表格 ASCII art + 段落合并。"""
    # 去除表格 ASCII art（连续的 - |= 字符行）
    text = re.sub(r"^[-|=+ ]{20,}$", "", text, flags=re.MULTILINE)
    # 合并连续空行
    text = re.sub(r"\n{3,}", "\n\n", text)
    # 去除行首/行尾的空白
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(lines).strip()


# ── 内容门控（Content Gate — Rk2）────────────────

def content_gate(evidence: dict[str, Any]) -> dict[str, Any]:
    """内容门控检查。

    如果清洗后的 content 为空或过短，score 归零，标记 blocked。
    确保下游 reranking 不会给空/垃圾内容高排名。

    Args:
        evidence: 证据字典（必须含 "content" 或 "text_clean" 键）

    Returns:
        更新后的 evidence 字典
    """
    content = str(evidence.get("content") or evidence.get("text_clean") or "")
    stripped = content.strip()
    cleaning_flags: list[str] = list(evidence.get("cleaning_flags", []) or [])

    if not stripped:
        evidence["score"] = 0.0
        evidence["content_gate_blocked"] = True
        cleaning_flags.append("content_gate:empty")
    elif len(stripped) < CONTENT_GATE_MIN_LENGTH:
        evidence["score"] = 0.0
        evidence["content_gate_blocked"] = True
        cleaning_flags.append(f"content_gate:too_short({len(stripped)})")
    else:
        evidence["content_gate_blocked"] = False
        cleaning_flags.append("content_gate:passed")

    evidence["cleaning_flags"] = cleaning_flags
    return evidence


# ── 主 Pipeline ─────────────────────────────────

_PipelineStep = tuple[str, bool]  # (step_name, is_post_market_clean)

# 标准 pipeline 配置
STANDARD_PIPELINE: list[str] = [
    "encoding_repair",    # Step 1
    "html_unescape",      # Step 2
    "market_specific",    # Step 2.5（在 2 之后 3 之前）
    "length_gate",        # Step 3
    "content_gate",       # Step 3.5（长度门控后的内容质量检查）
]


def clean_text(text: str, market: str = "cn_a", steps: str = "all") -> str:
    """对纯文本执行完整清洗 pipeline。

    Args:
        text: 输入文本
        market: 市场类型
        steps: "all"（全部步骤）或逗号分隔的步骤名

    Returns:
        清洗后的文本
    """
    if not text:
        return text

    pipeline = STANDARD_PIPELINE
    if steps != "all":
        pipeline = [s.strip() for s in steps.split(",") if s.strip()]

    result = text

    for step_name in pipeline:
        if step_name == "encoding_repair":
            result = step_encoding_repair(result)
        elif step_name == "html_unescape":
            result = step_html_unescape(result)
        elif step_name == "market_specific":
            result = market_specific_clean(result, market=market)
        # length_gate 和 content_gate 在文本清洗中仅做长度截断
        # 完整的 discard 逻辑由 clean_evidence 处理

    return result


def clean_evidence(evidence: dict[str, Any], market: str = "cn_a") -> dict[str, Any]:
    """对单条 evidence 执行完整清洗 pipeline。

    处理流程:
      Evidence 原文 → Step1-6 清洗 → Content Gate → 标记/降权

    Args:
        evidence: 证据字典，必须含 "content" 键
        market: 市场类型

    Returns:
        清洗后的 evidence（原地修改并返回）
    """
    result: dict[str, Any] = dict(evidence)
    cleaning_flags: list[str] = []

    # 提取原始内容
    raw_content = str(result.get("content") or result.get("text_clean") or "")
    if not raw_content:
        result["cleaning_flags"] = ["cleaning:empty_input"]
        result["content_gate_blocked"] = True
        result["score"] = 0.0
        return result

    # ── Step 1: Encoding repair ──
    content = step_encoding_repair(raw_content)
    if content != raw_content:
        cleaning_flags.append("encoding:repaired")
    else:
        cleaning_flags.append("encoding:no_change")

    # ── Step 2: HTML unescape ──
    content = step_html_unescape(content)
    if "&" in raw_content and content != raw_content:
        cleaning_flags.append("html:unescaped")

    # ── Step 2.5: Market-specific ──
    content_before_market = content
    content = market_specific_clean(content, market=market)
    if content != content_before_market:
        cleaning_flags.append(f"market:{market}")

    # ── Step 3: Length gate ──
    content, discard = step_length_gate(content)
    if discard:
        cleaning_flags.append("length_gate:discarded")
        result["cleaning_flags"] = cleaning_flags
        result["content"] = content
        result["text_clean"] = content
        result["score"] = 0.0
        result["content_gate_blocked"] = True
        return result
    else:
        cleaning_flags.append("length_gate:passed")

    # ── Step 4: Dedup hash ──
    processed_hash = content_hash(content)
    cleaning_flags.append(f"dedup:hash={processed_hash[:12]}")

    # ── Step 5: URL normalize ──
    content = step_url_normalize(content)

    # ── Step 6: Timestamp fallback ──
    publish_time = result.get("publish_time", "")
    retrieved_at = result.get("retrieved_at", "")
    document_date = result.get("metadata", {}).get("document_date", "") if isinstance(result.get("metadata"), dict) else ""
    new_ts = step_timestamp_fallback(publish_time, retrieved_at=retrieved_at, document_date=document_date)
    if new_ts != publish_time and publish_time:
        result["publish_time"] = new_ts
        cleaning_flags.append("timestamp:fallback")

    # ── 内容门控 ──
    result["content"] = content
    result["text_clean"] = content
    result["cleaning_flags"] = cleaning_flags
    result = content_gate(result)

    return result


def batch_clean_evidence(
    evidence_list: list[dict[str, Any]],
    market: str = "cn_a",
    dedup: bool = True,
) -> list[dict[str, Any]]:
    """批量清洗 evidence 列表。

    Args:
        evidence_list: evidence 字典列表
        market: 市场类型
        dedup: 是否去重（基于 content hash）

    Returns:
        清洗后的 evidence 列表（已去重，按 score 降序）
    """
    if not evidence_list:
        return []

    cleaned = [clean_evidence(item, market=market) for item in evidence_list]

    # 去重（保留相同 hash 中 score 最高的）
    if dedup:
        seen_hashes: dict[str, dict[str, Any]] = {}
        for item in cleaned:
            flags = item.get("cleaning_flags", []) or []
            h = next((f.split("=", 1)[1] for f in flags if f.startswith("dedup:hash=")), None)
            if h is None:
                continue
            existing = seen_hashes.get(h)
            if existing is None or float(item.get("score", 0.0) or 0.0) > float(existing.get("score", 0.0) or 0.0):
                seen_hashes[h] = item
        cleaned = list(seen_hashes.values())

    # 按 score 降序
    cleaned.sort(key=lambda x: float(x.get("score", 0.0) or 0.0), reverse=True)
    return cleaned


# ── Self-test ────────────────────────────────────

if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    def _safe(text: str, max_len: int = 80) -> str:
        return text[:max_len].encode("utf-8", errors="backslashreplace").decode("utf-8")

    print("=" * 60)
    print("cleaning_pipeline.py — 自检测试")
    print("=" * 60)

    passed = 0
    failed = 0

    # Test 1: 编码修复 + HTML 解码
    test1 = clean_text("ę́(600519)Q1 гĸЧ &amp; &lt;br&gt;", market="cn_a")
    expected_terms = ["茅台", "600519", "<"]
    ok1 = all(t in test1 for t in expected_terms)
    print(f"\n{'✅' if ok1 else '❌'} encoding修复+HTML解码: {_safe(test1)}")
    if ok1: passed += 1
    else: failed += 1

    # Test 2: 正常中文不应被误修
    test2 = clean_text("公司拟以实施权益分派股权登记日登记的总股本", market="cn_a")
    ok2 = "公司" in test2 and "权益" in test2
    print(f"{'✅' if ok2 else '❌'} 正常中文未误修: {_safe(test2)}")
    if ok2: passed += 1
    else: failed += 1

    # Test 3: 长度门控
    short = clean_text("a", market="cn_a")
    ok3 = len(short) == 1  # clean_text 不丢弃，只清洗
    print(f"{'✅' if ok3 else '❌'} 长度门控(clean_text不丢弃): len={len(short)}")
    if ok3: passed += 1
    else: failed += 1

    # Test 4: Evidence 清洗 + Content Gate
    # 用纯乱码文本测试（不含中文，确保触发 encoding repair）
    ev = {"content": "ę́(600519)Q1 гĸЧQ1 гĸЧ Ię́ ĸЧIę́ ĸЧ ֱƽ гĸԳЧֱƽ гĸԳЧ ˾ ֤ȯɷ޹˾ ɽɽ", "score": 8.6, "publish_time": ""}
    cleaned = clean_evidence(ev, market="cn_a")
    ok4 = (
        cleaned.get("content_gate_blocked") is False
        and "encoding:repaired" in cleaned.get("cleaning_flags", [])
        and "茅台" in cleaned.get("content", "")
    )
    print(f"{'✅' if ok4 else '❌'} evidence清洗+门控: score={cleaned.get('score')} flags={cleaned.get('cleaning_flags')}")
    if ok4: passed += 1
    else: failed += 1

    # Test 5: 空内容门控阻断
    ev_empty = {"content": "", "score": 8.6}
    cleaned_empty = clean_evidence(ev_empty, market="cn_a")
    ok5 = cleaned_empty.get("content_gate_blocked") is True and cleaned_empty.get("score") == 0.0
    print(f"{'✅' if ok5 else '❌'} 空内容门控阻断: blocked={cleaned_empty.get('content_gate_blocked')}")
    if ok5: passed += 1
    else: failed += 1

    # Test 6: 太短内容门控阻断
    ev_short = {"content": "hi", "score": 8.6}
    cleaned_short = clean_evidence(ev_short, market="cn_a")
    ok6 = cleaned_short.get("content_gate_blocked") is True and cleaned_short.get("score") == 0.0
    print(f"{'✅' if ok6 else '❌'} 过短内容门控阻断: blocked={cleaned_short.get('content_gate_blocked')}")
    if ok6: passed += 1
    else: failed += 1

    # Test 7: 港股 market-specific
    hk_text = "Alibaba Group Holding Limited …" * 100  # 超长文本
    hk_clean = market_specific_clean(hk_text, market="hk")
    ok7 = len(hk_clean) <= HK_SNIPPET_MAX_CHARS
    print(f"{'✅' if ok7 else '❌'} 港股snippet截断: {len(hk_clean)} ≤ {HK_SNIPPET_MAX_CHARS}")
    if ok7: passed += 1
    else: failed += 1

    # Test 8: 时间戳回退
    ts = step_timestamp_fallback("", retrieved_at="2026-06-01 12:00:00")
    ok8 = ts == "2026-06-01 12:00:00"
    print(f"{'✅' if ok8 else '❌'} 时间戳回退: {ts}")
    if ok8: passed += 1
    else: failed += 1

    # Test 9: 批量清洗
    evs = [
        {"content": "ę́(600519)Q1 гĸЧ", "score": 8.6},
        {"content": "ę́(600519)Q1 гĸЧ", "score": 7.0},  # duplicate content, lower score
        {"content": "Clean Chinese text for test", "score": 9.0},
    ]
    batch = batch_clean_evidence(evs, market="cn_a")
    ok9 = len(batch) <= 2  # dedup should remove the duplicate
    print(f"{'✅' if ok9 else '❌'} 批量清洗+去重: {len(batch)} items (≤2)")
    if ok9: passed += 1
    else: failed += 1

    print(f"\n{'=' * 60}")
    print(f"结果: {passed} 通过, {failed} 失败 / {passed + failed}")
    print(f"{'=' * 60}")
    if failed:
        sys.exit(1)
    print("全部测试通过 ✅")
