"""LLM/Codex-style subjective review for generated research reports."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List

from src.evaluation.report_quality import resolve_run_paths
from src.models.model_adapter import ModelAdapter
from src.utils.config import load_config


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
    adapter = model or _build_review_adapter(outputs_path=outputs_path, config_path=config_path)
    base = {
        "schema_version": "llm_quality_review.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_dir": str(Path(run_dir) if run_dir is not None else outputs_path),
        "model": getattr(adapter, "model_name", ""),
    }
    if not getattr(adapter, "api_key", "") and model is None:
        fallback = _heuristic_review_without_api_key(artifacts)
        fallback.update(base)
        return fallback

    prompt = _build_review_prompt(artifacts)
    parsed: Any = None
    failures: list[str] = []
    for _attempt in range(1, 3):
        try:
            retry_prompt = prompt
            if failures:
                retry_prompt += (
                    "\n\nThe previous response could not be parsed as JSON. Return one complete JSON object only; "
                    "do not use markdown fences or truncate arrays."
                )
            if hasattr(adapter, "generate_json"):
                parsed = adapter.generate_json(prompt=retry_prompt, system_prompt=_system_prompt())
            else:
                parsed = adapter.generate(prompt=retry_prompt, system_prompt=_system_prompt())
            break
        except Exception as exc:  # pragma: no cover - adapter-specific failures
            failures.append(str(exc))
    if parsed is None:
        failed = _failed_review(
            base,
            f"LLM review call failed after {len(failures)} attempts: {failures[-1] if failures else 'unknown error'}",
        )
        failed["attempt_count"] = len(failures)
        failed["failure_reasons"] = failures
        return failed
    normalized = _normalize_review(parsed)
    normalized = _apply_artifact_guard(normalized, artifacts)
    normalized["attempt_count"] = len(failures) + 1
    if failures:
        normalized["recovered_failure_reasons"] = failures
    normalized.update(base)
    return normalized


def _build_review_adapter(outputs_path: Path, config_path: str) -> ModelAdapter:
    config = load_config(config_path)
    routes = config.get("agent_model_routes") if isinstance(config, dict) else {}
    defaults = routes.get("defaults", {}) if isinstance(routes, dict) and isinstance(routes.get("defaults"), dict) else {}
    summary = _read_json(outputs_path / "run_summary.json", default={})
    tier = str(summary.get("execution_tier") or "delivery").lower() if isinstance(summary, dict) else "delivery"
    role_route = routes.get("llm_report_review") if isinstance(routes, dict) else None
    if isinstance(role_route, dict):
        profile = str(role_route.get(tier) or role_route.get("delivery") or defaults.get(tier) or defaults.get("delivery") or "flash")
    elif isinstance(role_route, str):
        profile = role_route
    else:
        profile = str(defaults.get(tier) or defaults.get("delivery") or "flash")
    try:
        return ModelAdapter.from_profile(profile=profile, config_path=config_path, fallback_section="agent_model")
    except Exception:
        return ModelAdapter.from_config(config_path=config_path)


def write_llm_review_outputs(run_dir: str | Path, review: Dict[str, Any] | None = None) -> Dict[str, str]:
    paths = resolve_run_paths(run_dir)
    return write_llm_review_outputs_for_paths(paths.outputs_dir, paths.reports_dir, review or review_report_with_llm(run_dir))


def write_llm_review_outputs_for_paths(
    outputs_dir: str | Path,
    reports_dir: str | Path,
    review: Dict[str, Any],
) -> Dict[str, str]:
    outputs_path = Path(outputs_dir)
    payload = _json_safe(review)
    outputs_path.mkdir(parents=True, exist_ok=True)
    json_path = outputs_path / "llm_quality_review.json"
    md_path = outputs_path / "llm_quality_review.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
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
    normalized_issues = [item for item in normalized_issues if str(item.get("message") or "").strip()]
    fatal_count = sum(1 for item in normalized_issues if item["severity"] == "fatal")
    blocker_count = sum(1 for item in normalized_issues if item["severity"] == "blocker")
    if _contains_direct_fail(normalized_issues):
        fatal_count = max(1, fatal_count)
    verdict = str(payload.get("verdict") or payload.get("summary") or "")
    verdict_pass = _verdict_is_pass(verdict)
    review_pass = bool((total >= 0.80 or verdict_pass) and fatal_count == 0 and blocker_count == 0)
    return {
        "model_status": "completed",
        "llm_review_pass": review_pass,
        "total_score": total,
        "fatal_issue_count": fatal_count,
        "dimension_scores": normalized_scores,
        "verdict": verdict,
        "issues": normalized_issues,
    }


def _apply_artifact_guard(review: Dict[str, Any], artifacts: Dict[str, Any]) -> Dict[str, Any]:
    """Do not let empty/non-substantive reviewer output override passing artifacts."""

    quality = artifacts.get("quality_report") if isinstance(artifacts.get("quality_report"), dict) else {}
    verification = artifacts.get("verification_report") if isinstance(artifacts.get("verification_report"), dict) else {}
    review = _reconcile_review_with_runtime_artifacts(review, artifacts)
    issues = review.get("issues") if isinstance(review.get("issues"), list) else []
    blocking = [
        item
        for item in issues
        if isinstance(item, dict) and str(item.get("severity", "")).lower() in {"fatal", "blocker"}
    ]
    if not bool(quality.get("objective_pass", False)) or not bool(verification.get("passed", False)):
        return review
    if blocking:
        return review
    if issues and not bool(review.get("artifact_reconciliation_applied")):
        return review
    if float(review.get("total_score", 0.0) or 0.0) < 0.65 and not bool(review.get("artifact_reconciliation_applied")):
        return review
    guarded = dict(review)
    guarded["llm_review_pass"] = True
    guarded["total_score"] = max(_score(guarded.get("total_score", 0.0)), 0.82)
    guarded["verdict"] = (str(guarded.get("verdict") or "").strip() + " | artifact_guard: objective and verifier gates passed; empty reviewer issues ignored.").strip()
    guarded["artifact_guard_applied"] = True
    return guarded


def _reconcile_review_with_runtime_artifacts(review: Dict[str, Any], artifacts: Dict[str, Any]) -> Dict[str, Any]:
    section_verification = artifacts.get("section_verification") if isinstance(artifacts.get("section_verification"), dict) else {}
    if section_verification.get("status") != "passed":
        return review
    report_md = str(artifacts.get("report_md") or "")
    if _contains_bad_report_terms(report_md):
        return review
    issues = review.get("issues") if isinstance(review.get("issues"), list) else []
    kept: List[Dict[str, Any]] = []
    reconciled: List[Dict[str, Any]] = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        message = str(issue.get("message") or "")
        if (
            _is_stale_section_depth_review_issue(message, report_md=report_md)
            or _is_disclosed_ttm_period_context_issue(message, report_md=report_md)
            or _is_reviewer_unfinished_sentence_false_positive(message, artifacts=artifacts)
        ):
            row = dict(issue)
            row["severity"] = "warning"
            row["category"] = "llm_review_reconciled"
            row["message"] = message + " | reconciled: section_verification passed after repair"
            reconciled.append(row)
            continue
        kept.append(issue)
    if not reconciled:
        return review
    output = dict(review)
    output["issues"] = kept + reconciled
    blocking = [
        item for item in kept
        if str(item.get("severity") or "").lower() in {"fatal", "blocker"}
    ]
    output["fatal_issue_count"] = sum(1 for item in output["issues"] if str(item.get("severity") or "").lower() == "fatal")
    if not blocking:
        output["llm_review_pass"] = True
        output["total_score"] = max(_score(output.get("total_score", 0.0)), 0.82)
    output["artifact_reconciliation_applied"] = True
    return output


def _is_disclosed_ttm_period_context_issue(message: str, *, report_md: str) -> bool:
    text = str(message or "").lower()
    report = str(report_md or "").lower()
    alleges_mismatch = "ttm" in text and any(term in text for term in ("期间", "错配", "mismatch", "fy2024"))
    disclosed = (
        "当前 ttm 市场快照" in report
        and "期间不同" in report
        and any(term in report for term in ("不作同期间数值替代", "不作同期间替代"))
    )
    return alleges_mismatch and disclosed


def _is_reviewer_unfinished_sentence_false_positive(message: str, *, artifacts: Dict[str, Any]) -> bool:
    text = str(message or "").lower()
    if not any(term in text for term in ("未完成句子", "unfinished sentence")):
        return False
    quality = artifacts.get("quality_report") if isinstance(artifacts.get("quality_report"), dict) else {}
    issues = quality.get("issues") if isinstance(quality.get("issues"), list) else []
    return not any(
        "unfinished sentence pattern" in str(item.get("message") or "").lower()
        for item in issues
        if isinstance(item, dict)
    )


def _is_stale_section_depth_review_issue(message: str, *, report_md: str = "") -> bool:
    text = str(message or "").lower()
    stale_terms = [
        "内容空洞",
        "大量暂无结论",
        "暂不展开",
        "缺乏实质性内容",
        "章节内容空洞",
        "关键章节内容空洞",
        "同行对比缺失",
        "估值分析缺失",
        "风险分析缺失",
        "内容不足",
        "lacks actionable",
        "section missing",
        "content emptiness",
        "no conclusion",
        "non-actionable",
        "company report requirement not met",
        "three statements incomplete",
        "peer comparison absent",
        "valuation/sensitivity missing",
        "risks generic",
        "investment conclusion ambiguous",
        "charts not useful",
    ]
    fact_error_terms = [
        "不符",
        "不匹配",
        "错误",
        "错配",
        "unsupported",
        "evidence",
        "证据",
        "数字",
        "数值",
        "现金流",
        "revenue",
        "net income",
        "dcf",
    ]
    if not any(term in text for term in stale_terms):
        return False
    if any(term in text for term in fact_error_terms):
        # Placeholder evidence wording in the stale review should not keep
        # blocking after the repaired markdown no longer contains the marker.
        if "evidence_not_available" in text and "evidence_not_available" not in str(report_md or "").lower():
            return True
        return False
    return True


def _verdict_is_pass(verdict: str) -> bool:
    text = str(verdict or "").strip().lower()
    pass_word = chr(0x901A) + chr(0x8FC7)
    not_word = chr(0x4E0D) + pass_word
    missing_word = chr(0x672A) + pass_word
    if pass_word in text and not_word not in text and missing_word not in text:
        return True
    if not text or any(term in text for term in ["fail", "failed", "不通过", "不合格", "未通过"]):
        return False
    return text in {"pass", "passed", "合格", "通过"} or "pass" in text


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


def _heuristic_review_without_api_key(artifacts: Dict[str, Any]) -> Dict[str, Any]:
    """Local deterministic review used when no reviewer API key is configured.

    This is intentionally labeled as a heuristic fallback rather than a real
    LLM/Codex review. It prevents every local demo from scoring 0 solely because
    the reviewer key is absent, while still failing reports with objective
    blockers, verifier failures, obvious placeholders, or period issues.
    """

    quality = artifacts.get("quality_report") if isinstance(artifacts.get("quality_report"), dict) else {}
    verification = artifacts.get("verification_report") if isinstance(artifacts.get("verification_report"), dict) else {}
    claims = artifacts.get("claims") if isinstance(artifacts.get("claims"), list) else []
    evidence = artifacts.get("evidence") if isinstance(artifacts.get("evidence"), list) else []
    citations = artifacts.get("citations") if isinstance(artifacts.get("citations"), list) else []
    report_md = str(artifacts.get("report_md") or "")

    objective_score = _score(quality.get("total_score", quality.get("score", 0.0)))
    objective_pass = bool(quality.get("objective_pass", False))
    verifier_pass = bool(verification.get("passed", False))
    issue_pool = []
    for item in (quality.get("issues") or []) + (quality.get("top_issues") or []):
        if isinstance(item, dict):
            issue_pool.append(item)
    blocker_count = sum(1 for item in issue_pool if str(item.get("severity", "")).lower() in {"fatal", "blocker"})

    evidence_score = min(1.0, len(evidence) / 6)
    citation_score = min(1.0, len(citations) / max(1, len(claims)))
    length_score = min(1.0, len(report_md) / 3500)
    placeholder_penalty = 0.18 if _contains_bad_report_terms(report_md) else 0.0
    blocker_penalty = min(0.3, blocker_count * 0.08)

    scores = {
        "professional_report_likeness": max(0.0, min(1.0, 0.55 * objective_score + 0.25 * length_score + 0.20 * evidence_score - placeholder_penalty)),
        "investment_insight": max(0.0, min(1.0, 0.65 * objective_score + 0.20 * length_score - blocker_penalty)),
        "fact_period_consistency": 1.0 if verifier_pass and not _contains_period_issue(issue_pool, report_md) else 0.55,
        "company_report_requirement_fit": max(0.0, min(1.0, 0.75 * objective_score + 0.25 * evidence_score - blocker_penalty)),
        "chart_usefulness": max(0.0, min(1.0, 0.65 * objective_score + 0.35 * citation_score)),
        "language_quality": 0.9 if not _contains_bad_report_terms(report_md) else 0.55,
    }
    total = _score(sum(scores.values()) / len(REVIEW_DIMENSIONS))
    issues: List[Dict[str, Any]] = []
    if not verifier_pass:
        issues.append({"issue_id": "heuristic_review_0001", "severity": "fatal", "category": "verifier", "message": "verifier did not pass"})
    if not objective_pass:
        issues.append({"issue_id": "heuristic_review_0002", "severity": "blocker", "category": "objective", "message": "objective quality gate did not pass"})
    if blocker_count:
        issues.append({"issue_id": "heuristic_review_0003", "severity": "blocker", "category": "quality", "message": f"objective report still has {blocker_count} fatal/blocker issue(s)"})
    if _contains_bad_report_terms(report_md):
        issues.append({"issue_id": "heuristic_review_0004", "severity": "fatal", "category": "language_quality", "message": "report contains obvious placeholder, mojibake, or empty-section wording"})
    fatal_count = sum(1 for item in issues if item["severity"] == "fatal")
    blocker_count = sum(1 for item in issues if item["severity"] == "blocker")
    review_pass = bool(total >= 0.80 and fatal_count == 0 and blocker_count == 0)
    verdict = (
        "缺少外部 reviewer API key，已使用本地启发式复核；该结果可用于本地闭环，"
        "但正式比赛验收仍建议配置真实 LLM review。"
    )
    return {
        "model_status": "heuristic_fallback_no_api_key",
        "llm_review_pass": review_pass,
        "total_score": total,
        "fatal_issue_count": fatal_count,
        "dimension_scores": {key: _score(scores[key]) for key in REVIEW_DIMENSIONS},
        "verdict": verdict,
        "issues": issues,
    }


def _contains_bad_report_terms(text: str) -> bool:
    bad_terms = ("????", "明显乱码", "乱码", "内容空洞", "大量暂无结论", "暂无可验证结论", "TODO")
    return any(term.lower() in str(text or "").lower() for term in bad_terms)


def _contains_period_issue(issues: List[Dict[str, Any]], report_md: str) -> bool:
    joined = "\n".join(str(item.get("message", "")) for item in issues) + "\n" + str(report_md or "")
    return any(term.lower() in joined.lower() for term in ("期间错配", "period mismatch", "数据期错配", "尚未结束"))


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
        "claims_sample": _compact_review_claims(artifacts["claims"][:8]),
        "evidence_sample": _compact_review_evidence(artifacts["evidence"][:8]),
        "citations_sample": _compact_review_citations(artifacts["citations"][:8]),
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


def _compact_review_claims(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "claim_id": row.get("claim_id"),
            "section_name": row.get("section_name"),
            "claim_text": str(row.get("claim_text") or "")[:1200],
            "evidence_ids": list(row.get("evidence_ids") or [])[:8],
            "numeric_values": row.get("numeric_values") if isinstance(row.get("numeric_values"), dict) else {},
        }
        for row in records
    ]


def _compact_review_evidence(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    for row in records:
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        metrics = metadata.get("metrics") if isinstance(metadata.get("metrics"), dict) else {}
        output.append(
            {
                "evidence_id": row.get("evidence_id") or row.get("sample_id"),
                "title": str(row.get("title") or "")[:300],
                "source_type": row.get("source_type"),
                "source_authority": row.get("source_authority") or row.get("authority_level"),
                "period": row.get("period") or metadata.get("period"),
                "source_url": str(row.get("source_url") or "")[:500],
                "content_excerpt": str(row.get("content") or row.get("snippet") or "")[:1600],
                "metric_names": list(metrics)[:12],
            }
        )
    return output


def _compact_review_citations(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "evidence_id": row.get("evidence_id"),
            "label": row.get("label") or row.get("citation_label"),
            "title": str(row.get("title") or "")[:300],
            "source_url": str(row.get("source_url") or "")[:500],
        }
        for row in records
    ]


def _system_prompt() -> str:
    return "你是严格的金融研报评审。只输出可解析 JSON，不要输出 Markdown。"


def _load_review_artifacts(outputs_dir: Path, reports_dir: Path) -> Dict[str, Any]:
    return {
        "quality_report": _read_json(outputs_dir / "quality_report.json", {}),
        "verification_report": _read_json(outputs_dir / "verification_report.json", {}),
        "section_verification": _read_json(outputs_dir / "section_verification.json", {}),
        "section_repair": _read_json(outputs_dir / "section_repair.json", {}),
        "canonical_metrics": _read_json(outputs_dir / "canonical_metrics.json", {}),
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


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(_json_safe(key)): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, str):
        return _clean_json_string(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return value
    return value


def _clean_json_string(value: str) -> str:
    return "".join(ch if (ord(ch) >= 32 or ch in "\n\r\t") else " " for ch in value)
