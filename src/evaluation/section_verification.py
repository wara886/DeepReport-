"""Deterministic section contract checks for formal report delivery."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import re
from typing import Any, Dict, List


CORE_SECTION_CONTRACTS = {
    "executive_summary": {"title": "执行摘要", "min_chars": 120, "min_paragraphs": 1},
    "business_overview": {"title": "业务概览", "min_chars": 160, "min_paragraphs": 1},
    "financial_analysis": {"title": "财务分析", "min_chars": 220, "min_paragraphs": 1},
    "valuation": {"title": "估值观察", "min_chars": 180, "min_paragraphs": 1},
    "risks": {"title": "风险评估", "min_chars": 160, "min_paragraphs": 1},
    "conclusion": {"title": "投资结论", "min_chars": 160, "min_paragraphs": 1},
}

PLACEHOLDER_MARKERS = (
    "本节暂不展开",
    "暂不展开详细分析",
    "需进一步分析",
    "下文章节展开分析",
    "暂无可验证结论",
    "框架待补",
    "估值分析待补",
    "敏感性分析框架待补",
    "cannot_verify",
    "no_conclusion",
    "cannot_judge",
)

UNFINISHED_TAILS = ("分别披露", "主要包括", "取决于", "由于", "因此", "以及", "包括", "体现为", "来自于")


def build_section_verification(
    *,
    markdown: str,
    report_section_contracts: Any = None,
    quality_remediation_plan: Any = None,
) -> Dict[str, Any]:
    """Build a deterministic section verification artifact."""

    text = str(markdown or "")
    contracts = _contracts(report_section_contracts)
    remediation = quality_remediation_plan if isinstance(quality_remediation_plan, dict) else {}
    issues: List[Dict[str, Any]] = []
    section_results: Dict[str, Dict[str, Any]] = {}

    for section_key, spec in CORE_SECTION_CONTRACTS.items():
        title = str(spec["title"])
        body = _section_body(text, title)
        char_count = _count_chars(body or "")
        paragraph_count = _paragraph_count(body or "")
        status = "passed"
        reasons: List[str] = []
        if body is None:
            status = "failed"
            reasons.append("missing_section")
        if body is not None and char_count < int(spec["min_chars"]):
            status = "failed"
            reasons.append("section_too_short")
        if body is not None and paragraph_count < int(spec["min_paragraphs"]):
            status = "failed"
            reasons.append("too_few_paragraphs")
        markers = [marker for marker in PLACEHOLDER_MARKERS if marker in (body or "")]
        if markers:
            status = "failed"
            reasons.append("placeholder_text")
        if _unfinished_tail(body or ""):
            status = "failed"
            reasons.append("unfinished_sentence_tail")
        contract = contracts.get(section_key) if isinstance(contracts.get(section_key), dict) else {}
        if contract.get("blocked_reasons") or contract.get("quality_flags") or contract.get("status") == "gap":
            status = "failed"
            reasons.append("contract_blocked")
        section_results[section_key] = {
            "title": title,
            "status": status,
            "char_count": char_count,
            "paragraph_count": paragraph_count,
            "min_chars": int(spec["min_chars"]),
            "min_paragraphs": int(spec["min_paragraphs"]),
            "reasons": sorted(set(reasons)),
            "placeholder_markers": markers,
        }
        for reason in sorted(set(reasons)):
            issues.append(
                {
                    "issue_id": f"section_contract_{section_key}_{reason}",
                    "severity": "blocker",
                    "category": "section_contract",
                    "section": section_key,
                    "message": f"{title} failed section contract: {reason}",
                    "source": "section_verification",
                }
            )

    for section in _string_list(remediation.get("failed_sections")):
        issues.append(
            {
                "issue_id": f"section_repair_pending_{section}",
                "severity": "blocker",
                "category": "section_repair",
                "section": section,
                "message": f"section repair still pending: {section}",
                "source": "quality_remediation_plan",
            }
        )

    failed_sections = sorted(
        {
            str(issue.get("section") or "")
            for issue in issues
            if issue.get("severity") in {"fatal", "blocker"} and str(issue.get("section") or "")
        }
    )
    return {
        "schema_version": "section_verification.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if not failed_sections else "failed",
        "formal_delivery_allowed": not failed_sections,
        "section_results": section_results,
        "failed_sections": failed_sections,
        "issue_count": len(issues),
        "issues": issues,
    }


def write_section_verification(
    output_dir: str | Path,
    *,
    markdown: str,
    report_section_contracts: Any = None,
    quality_remediation_plan: Any = None,
) -> Dict[str, Any]:
    artifact = build_section_verification(
        markdown=markdown,
        report_section_contracts=report_section_contracts,
        quality_remediation_plan=quality_remediation_plan,
    )
    path = Path(output_dir) / "section_verification.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return artifact


def _contracts(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    contracts = payload.get("contracts")
    return contracts if isinstance(contracts, dict) else {}


def _section_body(markdown: str, title: str) -> str | None:
    pattern = re.compile(rf"^##\s+{re.escape(title)}\s*$", re.MULTILINE)
    match = pattern.search(markdown)
    if not match:
        return None
    start = match.end()
    next_heading = re.search(r"^##\s+", markdown[start:], re.MULTILINE)
    end = start + next_heading.start() if next_heading else len(markdown)
    return markdown[start:end].strip()


def _count_chars(text: str) -> int:
    return len(re.sub(r"\s+", "", str(text or "")))


def _paragraph_count(text: str) -> int:
    return len([part for part in re.split(r"\n\s*\n", str(text or "").strip()) if part.strip()])


def _unfinished_tail(text: str) -> bool:
    tail = re.sub(r"\s+", "", str(text or ""))[-28:]
    return any(tail.endswith(marker) for marker in UNFINISHED_TAILS)


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []
