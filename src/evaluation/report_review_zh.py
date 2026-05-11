"""Generate Chinese-first human review views from existing baseline report artifacts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


SECTION_DISPLAY: Dict[str, str] = {
    "executive_summary": "执行摘要（Executive Summary）",
    "business_overview": "业务概览（Business Overview）",
    "financial_analysis": "财务分析（Financial Analysis）",
    "valuation": "估值（Valuation）",
    "risks": "风险评估（Risk Assessment）",
    "risk_assessment": "风险评估（Risk Assessment）",
    "conclusion": "结论（Conclusion）",
    "charts": "图表（Charts）",
}

SECTION_PRIORITY: Dict[str, str] = {
    "financial_analysis": "高优先级",
    "business_overview": "中优先级",
    "valuation": "低优先级",
    "risks": "低优先级",
    "risk_assessment": "低优先级",
    "executive_summary": "可暂时忽略",
    "conclusion": "可暂时忽略",
    "charts": "可暂时忽略",
}


@dataclass
class ClaimReviewRow:
    claim_id: str
    section_name: str
    claim_text: str
    claim_text_zh: str
    evidence_ids: List[str]
    confidence: float
    verifier_boundary_level: str
    nearest_collision_level: str
    focus_score: int
    focus_reason: str


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _extract_numbers(text: str) -> List[float]:
    numbers = []
    for m in re.finditer(r"-?\d+(?:\.\d+)?", str(text)):
        numbers.append(_safe_float(m.group(0), 0.0))
    return numbers


def _normalize_section_key(value: str) -> str:
    out = str(value or "").strip().lower()
    if out == "risk_assessment":
        return "risks"
    return out


def _translate_claim_text(claim_text: str) -> str:
    """Rule-based translation for review readability while preserving numbers."""

    text = str(claim_text).strip()
    patterns: List[Tuple[str, str]] = [
        (
            r"^([A-Za-z0-9_.-]+) reported revenue around ([0-9.]+B) in the available sample\.$",
            r"\1 在可用样本中的营收约为 \2。",
        ),
        (
            r"^([A-Za-z0-9_.-]+) gross margin is estimated near ([0-9.]+%)\.$",
            r"\1 的毛利率估计约为 \2。",
        ),
        (
            r"^([A-Za-z0-9_.-]+) revenue growth is estimated near ([0-9.]+%) in the sample period\.$",
            r"\1 在样本期间的营收增速估计约为 \2。",
        ),
        (
            r"^([A-Za-z0-9_.-]+) net margin is approximately ([0-9.]+%)\.$",
            r"\1 的净利率约为 \2。",
        ),
        (
            r"^([A-Za-z0-9_.-]+) return on equity \(ROE\) is around ([0-9.]+%)\.$",
            r"\1 的净资产收益率（ROE）约为 \2。",
        ),
        (
            r"^([A-Za-z0-9_.-]+) return on assets \(ROA\) is around ([0-9.]+%)\.$",
            r"\1 的总资产收益率（ROA）约为 \2。",
        ),
        (
            r"^([A-Za-z0-9_.-]+) operating cash flow is estimated near ([0-9.]+B)\.$",
            r"\1 的经营现金流估计约为 \2。",
        ),
        (
            r"^([A-Za-z0-9_.-]+) currently has ([0-9.]+) evidence rows from ([0-9.]+) source types\.$",
            r"\1 当前有 \2 条证据，来自 \3 种来源类型。",
        ),
        (
            r"^([A-Za-z0-9_.-]+) ranks #([0-9.]+) by average trust-weighted evidence quality in current peer set\.$",
            r"\1 在当前同业中按平均信任加权证据质量排名第 \2。",
        ),
        (
            r"^([A-Za-z0-9_.-]+) has a low risk signal level with ratio ([0-9.]+)\.$",
            r"\1 的风险信号水平较低，风险比率为 \2。",
        ),
    ]
    for pattern, repl in patterns:
        if re.match(pattern, text):
            return re.sub(pattern, repl, text)

    fallback_replacements = [
        ("in the available sample period", "在可用样本期间"),
        ("in the available sample", "在可用样本中"),
        ("the sample period", "样本期间"),
        ("is estimated near", "估计约为"),
        ("is approximately", "约为"),
        ("is around", "约为"),
    ]
    out = text
    for old, new in fallback_replacements:
        out = out.replace(old, new)
    if out.endswith("."):
        out = f"{out[:-1]}。"
    elif not out.endswith("。"):
        out = f"{out}。"
    return out


def _verifier_boundary_level(confidence: float, threshold: float) -> str:
    gap = abs(confidence - threshold)
    if gap <= 0.03:
        return "高"
    if gap <= 0.08:
        return "中"
    return "低"


def _nearest_collision_level(claim_text: str, numeric_values: Dict[str, object]) -> str:
    text = str(claim_text).lower()
    nums = _extract_numbers(claim_text)
    keywords_high = ("revenue", "growth", "yoy", "margin", "eps", "cash flow")
    if any(k in text for k in keywords_high):
        if len(nums) >= 2:
            ordered = sorted(nums)
            for i in range(1, len(ordered)):
                if abs(ordered[i] - ordered[i - 1]) <= max(1.0, 0.03 * max(abs(ordered[i]), 1.0)):
                    return "高"
        return "中"

    if any("unit" in str(k).lower() or "period" in str(k).lower() for k in numeric_values.keys()):
        return "中"
    return "低"


def _section_weight(section_name: str) -> int:
    key = _normalize_section_key(section_name)
    if key == "financial_analysis":
        return 30
    if key == "business_overview":
        return 20
    if key in {"valuation", "risks"}:
        return 10
    return 0


def _priority_label(section_name: str) -> str:
    key = _normalize_section_key(section_name)
    return SECTION_PRIORITY.get(key, "低优先级")


def _display_section_name(section_name: str) -> str:
    key = _normalize_section_key(section_name)
    return SECTION_DISPLAY.get(key, section_name)


def _resolve_case_paths(report_md_path: Path) -> Tuple[Path, Path]:
    reports_dir = report_md_path.parent
    case_root = reports_dir.parent
    claim_table = case_root / "outputs" / "claim_table.json"
    verification = case_root / "outputs" / "verification_report.json"
    return claim_table, verification


def _load_threshold(project_root: Path) -> float:
    path = project_root / "data" / "outputs" / "checkpoints" / "verifier_checkpoint.json"
    if not path.exists():
        return 0.75
    data = dict(_read_json(path))
    return _safe_float(data.get("confidence_threshold", 0.75), 0.75)


def generate_report_review_zh(
    report_md_path: str | Path,
    project_root: str | Path | None = None,
) -> Dict[str, str]:
    """Generate report_review_zh.md and review_focus_summary.md from existing artifacts."""

    report_path = Path(report_md_path).resolve()
    if not report_path.exists():
        raise FileNotFoundError(f"report.md not found: {report_path}")

    root = Path(project_root).resolve() if project_root else Path(__file__).resolve().parents[2]
    claim_table_path, verification_path = _resolve_case_paths(report_path)
    if not claim_table_path.exists():
        raise FileNotFoundError(f"claim_table.json not found: {claim_table_path}")
    if not verification_path.exists():
        raise FileNotFoundError(f"verification_report.json not found: {verification_path}")

    threshold = _load_threshold(root)
    claims = list(_read_json(claim_table_path))
    verification = dict(_read_json(verification_path))

    rows: List[ClaimReviewRow] = []
    for claim in claims:
        item = dict(claim)
        claim_id = str(item.get("claim_id", "")).strip()
        section_name = str(item.get("section_name", "")).strip()
        claim_text = str(item.get("claim_text", "")).strip()
        evidence_ids = [str(x) for x in list(item.get("evidence_ids", []))]
        confidence = _safe_float(item.get("confidence", 0.0), 0.0)
        numeric_values = dict(item.get("numeric_values", {}))
        boundary = _verifier_boundary_level(confidence, threshold)
        collision = _nearest_collision_level(claim_text, numeric_values)
        collision_score = 10 if collision == "高" else 6 if collision == "中" else 2
        boundary_score = 8 if boundary == "高" else 4 if boundary == "中" else 1
        focus_score = _section_weight(section_name) + collision_score + boundary_score
        focus_reason = (
            f"章节优先级={_priority_label(section_name)}；"
            f"验证阈值边界风险={boundary}（confidence={confidence:.2f}, threshold={threshold:.2f}）；"
            f"近邻数字碰撞风险={collision}"
        )
        rows.append(
            ClaimReviewRow(
                claim_id=claim_id,
                section_name=section_name,
                claim_text=claim_text,
                claim_text_zh=_translate_claim_text(claim_text),
                evidence_ids=evidence_ids,
                confidence=confidence,
                verifier_boundary_level=boundary,
                nearest_collision_level=collision,
                focus_score=focus_score,
                focus_reason=focus_reason,
            )
        )

    grouped: Dict[str, List[ClaimReviewRow]] = {}
    for row in rows:
        grouped.setdefault(_normalize_section_key(row.section_name), []).append(row)

    review_md = report_path.parent / "report_review_zh.md"
    summary_md = report_path.parent / "review_focus_summary.md"

    lines: List[str] = []
    lines.append("# 人工审核中文视图（report_review_zh）")
    lines.append("")
    lines.append("- 说明：本文件仅用于人工审核，不替代 baseline `report.md`。")
    lines.append(f"- 验证阈值（verifier threshold）：{threshold:.2f}")
    lines.append(f"- Claim 总数：{len(rows)}")
    lines.append("")

    ordered_sections = [
        "financial_analysis",
        "business_overview",
        "valuation",
        "risks",
        "executive_summary",
        "conclusion",
        "charts",
    ]
    seen = set()
    for sec in ordered_sections + [k for k in grouped.keys() if k not in ordered_sections]:
        if sec in seen:
            continue
        seen.add(sec)
        section_rows = grouped.get(sec, [])
        lines.append(f"## {_display_section_name(sec)}｜优先级：{_priority_label(sec)}")
        lines.append("")
        if not section_rows:
            lines.append("- 本章节无 claim，可暂不审核。")
            lines.append("")
            continue
        for idx, row in enumerate(section_rows, start=1):
            lines.append(f"{idx}. Claim ID：`{row.claim_id}`")
            lines.append(f"   - 英文原文：{row.claim_text}")
            lines.append(f"   - 中文审核句：{row.claim_text_zh}")
            lines.append(f"   - evidence_ids：{', '.join(row.evidence_ids) if row.evidence_ids else '无'}")
            lines.append(f"   - confidence：{row.confidence:.2f}")
            lines.append("   - 审核提示：")
            lines.append(
                f"     - 优先检查验证阈值（verifier threshold）边界：风险={row.verifier_boundary_level}（confidence 与阈值距离越小越应优先核查）"
            )
            lines.append(
                f"     - 优先检查近邻数字碰撞（nearest_number_collision）风险：风险={row.nearest_collision_level}（特别关注 revenue / yoy / unit / period）"
            )
        lines.append("")

    review_md.write_text("\n".join(lines), encoding="utf-8")

    focus_rows = sorted(rows, key=lambda r: r.focus_score, reverse=True)
    top_k = focus_rows[: min(6, len(focus_rows))]

    summary_lines: List[str] = []
    summary_lines.append("# 中文审核摘要（review_focus_summary）")
    summary_lines.append("")
    summary_lines.append("- 本 case 建议先看以下 claim（按优先级排序）：")
    summary_lines.append("")
    for i, row in enumerate(top_k, start=1):
        summary_lines.append(
            f"{i}. `{row.claim_id}`｜{_display_section_name(row.section_name)}｜focus_score={row.focus_score}"
        )
        summary_lines.append(f"   - 为什么先看：{row.focus_reason}")
        summary_lines.append(f"   - 建议先对照：evidence_ids={', '.join(row.evidence_ids) if row.evidence_ids else '无'}")
    summary_lines.append("")
    summary_lines.append("## 对照文件路径")
    summary_lines.append("")
    summary_lines.append(f"- 验证报告（verification_report.json）：`{verification_path}`")
    summary_lines.append(f"- Claim 表（claim_table.json）：`{claim_table_path}`")
    summary_lines.append(f"- baseline 报告（report.md）：`{report_path}`")
    summary_lines.append(
        f"- 验证统计：passed={verification.get('passed')}，error_count={verification.get('error_count')}，warning_count={verification.get('warning_count')}，claim_count={verification.get('claim_count')}"
    )
    summary_md.write_text("\n".join(summary_lines), encoding="utf-8")

    return {
        "report_review_zh_md": str(review_md),
        "review_focus_summary_md": str(summary_md),
    }
