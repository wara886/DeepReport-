"""Build remediation plans from delivery quality gates.

The remediation plan is operational guidance for the next run. It is never
evidence and must not be cited as a source in the report.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List

from src.evaluation.report_quality import resolve_run_paths


EMPTY_PHRASES = ["暂无结论", "暂无可验证结论", "无法判断", "待补充", "框架性结论"]


def build_quality_remediation_plan(run_dir: str | Path) -> Dict[str, Any]:
    paths = resolve_run_paths(run_dir)
    return build_quality_remediation_plan_from_outputs(paths.outputs_dir, paths.run_dir)


def build_quality_remediation_plan_from_outputs(
    outputs_dir: str | Path,
    run_dir: str | Path | None = None,
) -> Dict[str, Any]:
    outputs = Path(outputs_dir)
    summary = _read_json(outputs / "run_summary.json", {})
    delivery_gate = _read_json(outputs / "delivery_gate.json", {})
    quality = _read_json(outputs / "quality_report.json", {})
    llm_review = _read_json(outputs / "llm_quality_review.json", {})
    issues = _normalize_issues(delivery_gate.get("issues") or delivery_gate.get("top_issues") or [])
    if not issues:
        issues = _normalize_issues((quality.get("issues") or []) + (llm_review.get("issues") or []))

    required_fixes = _required_fixes(issues, quality, llm_review)
    failed_sections = _failed_sections(issues)
    forbidden_patterns = _forbidden_patterns(issues)
    summary_text = _summary_text(summary, delivery_gate, issues, required_fixes)
    return {
        "schema_version": "quality_remediation_plan.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_dir": str(Path(run_dir) if run_dir is not None else outputs),
        "symbol": str(summary.get("symbol") or ""),
        "period": str(summary.get("period") or ""),
        "delivery_pass": bool(delivery_gate.get("delivery_pass", False)),
        "quality_feedback_used": bool(issues),
        "issue_counts": dict(delivery_gate.get("issue_counts") or {}),
        "failed_sections": failed_sections,
        "required_fixes": required_fixes,
        "forbidden_patterns": forbidden_patterns,
        "top_issues": issues[:8],
        "planner_constraints": _planner_constraints(required_fixes, forbidden_patterns),
        "memory_note": summary_text,
        "boundary": "Quality feedback is planning context only; report facts still require evidence_id citations and verifier gates.",
    }


def write_quality_remediation_plan(run_dir: str | Path, plan: Dict[str, Any] | None = None) -> Dict[str, str]:
    paths = resolve_run_paths(run_dir)
    return write_quality_remediation_plan_for_outputs(paths.outputs_dir, plan or build_quality_remediation_plan(run_dir))


def write_quality_remediation_plan_for_outputs(outputs_dir: str | Path, plan: Dict[str, Any]) -> Dict[str, str]:
    outputs = Path(outputs_dir)
    outputs.mkdir(parents=True, exist_ok=True)
    path = outputs / "quality_remediation_plan.json"
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    _update_run_summary(outputs / "run_summary.json", path, plan)
    return {"quality_remediation_plan": str(path)}


def _normalize_issues(items: List[Any]) -> List[Dict[str, Any]]:
    severity_order = {"fatal": 0, "blocker": 1, "warning": 2, "info": 3}
    rows: List[Dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        if isinstance(item, dict):
            rows.append(
                {
                    "issue_id": str(item.get("issue_id") or f"quality_{index:04d}"),
                    "severity": str(item.get("severity") or "warning"),
                    "category": str(item.get("category") or item.get("source") or "quality"),
                    "message": str(item.get("message") or item.get("detail") or ""),
                    "source": str(item.get("source") or "quality"),
                }
            )
        else:
            rows.append(
                {
                    "issue_id": f"quality_{index:04d}",
                    "severity": "warning",
                    "category": "quality",
                    "message": str(item),
                    "source": "quality",
                }
            )
    rows.sort(key=lambda row: (severity_order.get(row["severity"], 9), row["category"], row["issue_id"]))
    return rows


def _required_fixes(issues: List[Dict[str, Any]], quality: Dict[str, Any], llm_review: Dict[str, Any]) -> List[str]:
    text = " ".join(issue["message"] for issue in issues)
    fixes: List[str] = []
    if any(term in text for term in ["三表", "利润表", "资产负债表", "现金流量表"]):
        fixes.append("补齐利润表、资产负债表、现金流量表三表摘要，并写入正文财务分析章节。")
    if any(term in text for term in ["估值", "P/E", "P/B", "P/S"]):
        fixes.append("补充最小估值路径；若不可用，写明缺失数据源、缺口和对投资判断的影响。")
    if any(term in text for term in ["同行", "对比"]):
        fixes.append("补充同行对比表和可读结论，避免只输出框架。")
    if any(term in text for term in ["内容空洞", "框架", "暂无结论", "投资洞察"]):
        fixes.append("重写空洞章节，给出业务含义、投资判断和关键风险，不得大量使用暂无结论。")
    if any(term in text for term in ["敏感性", "情景"]):
        fixes.append("补充至少一个关键变量的敏感性分析，并在正文解释方向和影响。")
    if any(term in text for term in ["投资建议", "投资结论"]):
        fixes.append("投资结论必须包含方向、理由、关键证据和风险约束。")
    required = quality.get("required_checks", {}) if isinstance(quality.get("required_checks"), dict) else {}
    if required and not required.get("passed", True):
        fixes.append(f"修复 objective gate 未通过项：{', '.join(_failed_required_keys(required))}。")
    if llm_review.get("llm_review_pass") is False:
        fixes.append("优先处理 LLM 主观复核指出的 fatal/blocker 问题。")
    return _dedupe(fixes) or ["保持当前质量门禁结果，并继续提升专业深度和可读性。"]


def _failed_sections(issues: List[Dict[str, Any]]) -> List[str]:
    mapping = [
        ("executive_summary", ["执行摘要"]),
        ("three_statement_analysis", ["三表", "利润表", "资产负债表", "现金流量表"]),
        ("business_profile", ["业务", "画像", "主营"]),
        ("peer_comparison", ["同行", "对比"]),
        ("valuation", ["估值", "P/E", "P/B", "P/S"]),
        ("sensitivity", ["敏感性", "情景"]),
        ("risk", ["风险"]),
        ("investment_conclusion", ["投资建议", "投资结论"]),
    ]
    text = " ".join(issue["message"] for issue in issues)
    return [name for name, terms in mapping if any(term in text for term in terms)]


def _forbidden_patterns(issues: List[Dict[str, Any]]) -> List[str]:
    text = " ".join(issue["message"] for issue in issues)
    patterns = list(EMPTY_PHRASES)
    if "内容空洞" in text or "框架" in text:
        patterns.extend(["仅给出框架性描述", "缺少实质投资洞察"])
    return _dedupe(patterns)


def _planner_constraints(required_fixes: List[str], forbidden_patterns: List[str]) -> List[str]:
    constraints = list(required_fixes)
    if forbidden_patterns:
        constraints.append("禁止再次出现空洞表达：" + "、".join(forbidden_patterns[:5]) + "。")
    constraints.append("所有事实和数值仍必须绑定 evidence_id/citation，并通过 verifier。")
    return constraints


def _summary_text(
    summary: Dict[str, Any],
    delivery_gate: Dict[str, Any],
    issues: List[Dict[str, Any]],
    required_fixes: List[str],
) -> str:
    symbol = summary.get("symbol") or "unknown"
    period = summary.get("period") or "unknown"
    gate = delivery_gate.get("delivery_pass")
    top = "; ".join(issue["message"] for issue in issues[:3])
    fixes = "; ".join(required_fixes[:3])
    return f"Quality feedback for {symbol} {period}: delivery_pass={gate}; issues={top}; next fixes={fixes}"


def _failed_required_keys(required: Dict[str, Any]) -> List[str]:
    details = required.get("details")
    if isinstance(details, dict):
        return [key for key, value in details.items() if value is False]
    return [key for key, value in required.items() if key != "passed" and value is False]


def _update_run_summary(path: Path, plan_path: Path, plan: Dict[str, Any]) -> None:
    summary = _read_json(path, {})
    if not isinstance(summary, dict):
        summary = {}
    summary["quality_remediation_plan_path"] = str(plan_path)
    summary["quality_feedback_used"] = bool(plan.get("quality_feedback_used", False))
    summary["memory_quality_feedback_used"] = bool(plan.get("quality_feedback_used", False))
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def _dedupe(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default
    return payload
