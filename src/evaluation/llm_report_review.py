"""LLM/Codex-style subjective review for generated research reports."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List

from src.evaluation.report_quality import resolve_run_paths
from src.models.model_adapter import ModelAdapter


REVIEW_DIMENSIONS = [
    "professional_report_likeness",
    "investment_insight",
    "fact_period_consistency",
    "company_report_requirement_fit",
    "chart_usefulness",
    "language_quality",
]


def review_report_with_llm(
    run_dir: str | Path,
    config_path: str = "configs/model_backends.yaml",
    model: Any | None = None,
) -> Dict[str, Any]:
    paths = resolve_run_paths(run_dir)
    return review_report_with_llm_from_paths(
        outputs_dir=paths.outputs_dir,
        reports_dir=paths.reports_dir,
        run_dir=paths.run_dir,
        config_path=config_path,
        model=model,
    )


def review_report_with_llm_from_paths(
    outputs_dir: str | Path,
    reports_dir: str | Path,
    run_dir: str | Path | None = None,
    config_path: str = "configs/model_backends.yaml",
    model: Any | None = None,
) -> Dict[str, Any]:
    outputs_path = Path(outputs_dir)
    reports_path = Path(reports_dir)
    artifacts = _load_review_artifacts(outputs_path, reports_path)
    adapter = model or ModelAdapter.from_config(config_path=config_path)
    base = {
        "schema_version": "llm_quality_review.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_dir": str(Path(run_dir) if run_dir is not None else outputs_path),
        "model": getattr(adapter, "model_name", ""),
    }
    if not getattr(adapter, "api_key", "") and model is None:
        return {
            **base,
            "model_status": "missing_api_key",
            "llm_review_pass": False,
            "total_score": 0.0,
            "fatal_issue_count": 1,
            "dimension_scores": {key: 0.0 for key in REVIEW_DIMENSIONS},
            "verdict": "LLM/Codex 主观复核未运行：缺少 API key，不能假装通过。",
            "issues": [
                {
                    "issue_id": "llm_review_0001",
                    "severity": "fatal",
                    "category": "llm_review",
                    "message": "missing API key; subjective review skipped and delivery gate must fail",
                }
            ],
        }

    prompt = _build_review_prompt(artifacts)
    try:
        if hasattr(adapter, "generate_json"):
            parsed = adapter.generate_json(prompt=prompt, system_prompt=_system_prompt())
        else:
            parsed = adapter.generate(prompt=prompt, system_prompt=_system_prompt())
    except Exception as exc:  # pragma: no cover - defensive fallback
        return _failed_review(base, f"LLM review call failed: {exc}")
    normalized = _normalize_review(parsed)
    normalized.update(base)
    return normalized


def write_llm_review_outputs(run_dir: str | Path, review: Dict[str, Any] | None = None) -> Dict[str, str]:
    paths = resolve_run_paths(run_dir)
    return write_llm_review_outputs_for_paths(paths.outputs_dir, paths.reports_dir, review or review_report_with_llm(run_dir))


def write_llm_review_outputs_for_paths(
    outputs_dir: str | Path,
    reports_dir: str | Path,
    review: Dict[str, Any],
) -> Dict[str, str]:
    outputs_path = Path(outputs_dir)
    payload = review
    outputs_path.mkdir(parents=True, exist_ok=True)
    json_path = outputs_path / "llm_quality_review.json"
    md_path = outputs_path / "llm_quality_review.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_llm_review_markdown(payload), encoding="utf-8")
    return {"llm_quality_review": str(json_path), "llm_quality_review_md": str(md_path)}


def render_llm_review_markdown(review: Dict[str, Any]) -> str:
    lines = [
        "# LLM/Codex Quality Review",
        "",
        f"- llm_review_pass: `{review.get('llm_review_pass')}`",
        f"- total_score: `{review.get('total_score')}`",
        f"- model_status: `{review.get('model_status', 'completed')}`",
        "",
        "## Verdict",
        "",
        str(review.get("verdict", "")),
        "",
        "## Dimension Scores",
        "",
    ]
    for key, value in dict(review.get("dimension_scores", {})).items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Issues", ""])
    issues = review.get("issues", []) or []
    if not issues:
        lines.append("- No issues.")
    for issue in issues:
        lines.append(f"- **{issue.get('severity')} / {issue.get('category')}**: {issue.get('message')}")
    return "\n".join(lines) + "\n"


def _normalize_review(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return _failed_review({}, "LLM review did not return a JSON object")
    scores = payload.get("dimension_scores") if isinstance(payload.get("dimension_scores"), dict) else {}
    normalized_scores = {key: _score(scores.get(key, payload.get(key, 0.0))) for key in REVIEW_DIMENSIONS}
    total = _score(payload.get("total_score", sum(normalized_scores.values()) / len(REVIEW_DIMENSIONS)))
    issues = payload.get("issues") if isinstance(payload.get("issues"), list) else []
    normalized_issues = [_normalize_issue(item, index) for index, item in enumerate(issues, start=1)]
    fatal_count = sum(1 for item in normalized_issues if item["severity"] == "fatal")
    if _contains_direct_fail(normalized_issues):
        fatal_count = max(1, fatal_count)
    review_pass = bool(total >= 0.80 and fatal_count == 0)
    return {
        "model_status": "completed",
        "llm_review_pass": review_pass,
        "total_score": total,
        "fatal_issue_count": fatal_count,
        "dimension_scores": normalized_scores,
        "verdict": str(payload.get("verdict") or payload.get("summary") or ""),
        "issues": normalized_issues,
    }


def _failed_review(base: Dict[str, Any], message: str) -> Dict[str, Any]:
    return {
        **base,
        "model_status": "error",
        "llm_review_pass": False,
        "total_score": 0.0,
        "fatal_issue_count": 1,
        "dimension_scores": {key: 0.0 for key in REVIEW_DIMENSIONS},
        "verdict": message,
        "issues": [{"issue_id": "llm_review_0001", "severity": "fatal", "category": "llm_review", "message": message}],
    }


def _normalize_issue(item: Any, index: int) -> Dict[str, Any]:
    if isinstance(item, str):
        return {"issue_id": f"llm_review_{index:04d}", "severity": _severity_from_text(item), "category": "llm_review", "message": item}
    if not isinstance(item, dict):
        return {"issue_id": f"llm_review_{index:04d}", "severity": "warning", "category": "llm_review", "message": str(item)}
    message = str(item.get("message") or item.get("issue") or item.get("detail") or "")
    severity = str(item.get("severity") or _severity_from_text(message)).lower()
    if severity not in {"fatal", "blocker", "warning", "info"}:
        severity = _severity_from_text(message)
    return {
        "issue_id": str(item.get("issue_id") or f"llm_review_{index:04d}"),
        "severity": severity,
        "category": str(item.get("category") or "llm_review"),
        "message": message,
    }


def _contains_direct_fail(issues: List[Dict[str, Any]]) -> bool:
    bad_terms = ("内容空洞", "大量暂无结论", "期间错配", "明显乱码", "乱码", "empty", "period mismatch")
    joined = "\n".join(issue.get("message", "") for issue in issues)
    return any(term.lower() in joined.lower() for term in bad_terms)


def _severity_from_text(text: str) -> str:
    lowered = str(text or "").lower()
    if any(term in lowered for term in ["fatal", "明显乱码", "期间错配", "内容空洞", "大量暂无结论"]):
        return "fatal"
    if any(term in lowered for term in ["blocker", "缺少", "不可交付"]):
        return "blocker"
    return "warning"


def _score(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return round(max(0.0, min(1.0, number)), 4)


def _build_review_prompt(artifacts: Dict[str, Any]) -> str:
    contest_criteria = """
你要按金融研报比赛标准复核公司/个股研报。重点判断：
1. 是否像专业研报，而不是 artifacts 摘要；
2. 是否有投资洞察和原创分析；
3. 是否有明显事实、期间、口径错误；
4. 是否满足公司/个股赛题要求：三表、股权/业务画像、同行对比、估值/敏感性、风险、投资建议；
5. 图表是否真的有助分析；
6. 语言是否流畅、专业、可读。
若发现“内容空洞 / 大量暂无结论 / 期间错配 / 明显乱码”，必须给 fatal issue。
"""
    payload = {
        "objective_quality_report": artifacts["quality_report"],
        "verification_report": artifacts["verification_report"],
        "claims_sample": artifacts["claims"][:8],
        "evidence_sample": artifacts["evidence"][:8],
        "citations_sample": artifacts["citations"][:8],
        "report_markdown": artifacts["report_md"][:18000],
    }
    return (
        contest_criteria
        + "\n请只输出 JSON object，字段：total_score, dimension_scores, verdict, issues。\n"
        + "dimension_scores 必须包含："
        + ", ".join(REVIEW_DIMENSIONS)
        + "\n输入：\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def _system_prompt() -> str:
    return "你是严格的金融研报评审。只输出可解析 JSON，不要输出 Markdown。"


def _load_review_artifacts(outputs_dir: Path, reports_dir: Path) -> Dict[str, Any]:
    return {
        "quality_report": _read_json(outputs_dir / "quality_report.json", {}),
        "verification_report": _read_json(outputs_dir / "verification_report.json", {}),
        "claims": _as_list(_read_json(outputs_dir / "claims.json", [])),
        "evidence": _as_list(_read_json(outputs_dir / "evidence.json", [])),
        "citations": _as_list(_read_json(outputs_dir / "citations.json", [])),
        "report_md": _read_text(reports_dir / "report.md"),
    }


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _as_list(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []
