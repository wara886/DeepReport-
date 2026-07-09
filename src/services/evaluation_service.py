"""Read-only evaluation center aggregation for the workbench."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from typing import Any

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session, selectinload

from src.db.models import ClaimEvidence, LLMRun, ReportClaim, ReportTask
from src.services.report_task_service import ReportTaskNotFound


VERIFIED_CLAIM_STATUSES = {"supported", "verified", "passed"}
FAILED_CLAIM_STATUSES = {"failed", "unsupported", "missing_evidence", "numeric_mismatch"}
PASS_CHECK_STATUSES = {"passed", "supported", "verified", "ok", "success", "not_required"}
FAIL_CHECK_STATUSES = {"failed", "unsupported", "mismatch", "numeric_mismatch", "citation_missing"}


class EvaluationService:
    """Build product-facing quality and harness metrics from existing tables."""

    def __init__(self, *, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    def summary(self, *, limit: int = 50) -> dict[str, Any]:
        limit = max(1, min(int(limit or 50), 100))
        with self.session_factory() as session:
            active_task_condition = ReportTask.status != "archived"
            active_tasks = list(
                session.scalars(
                    select(ReportTask)
                    .where(active_task_condition)
                    .options(selectinload(ReportTask.claims).selectinload(ReportClaim.evidence_links))
                    .order_by(ReportTask.created_at.desc(), ReportTask.id.desc())
                    .limit(limit)
                )
                .unique()
                .all()
            )
            active_task_count = int(session.scalar(select(func.count(ReportTask.id)).where(active_task_condition)) or 0)
            completed_task_count = int(
                session.scalar(select(func.count(ReportTask.id)).where(active_task_condition, ReportTask.status == "completed"))
                or 0
            )
            quality_scores = [
                float(value)
                for value in session.scalars(
                    select(ReportTask.quality_score).where(active_task_condition, ReportTask.quality_score.is_not(None))
                ).all()
                if isinstance(value, int | float)
            ]
            claims = list(
                session.scalars(
                    select(ReportClaim)
                    .join(ReportTask, ReportTask.task_id == ReportClaim.task_id)
                    .where(active_task_condition)
                    .options(selectinload(ReportClaim.evidence_links))
                )
                .unique()
                .all()
            )
            claim_count = len(claims)
            traceable_claim_count = sum(1 for claim in claims if claim.evidence_links)
            verified_claim_count = sum(1 for claim in claims if claim.verification_status in VERIFIED_CLAIM_STATUSES)
            failed_claim_count = sum(1 for claim in claims if claim.verification_status in FAILED_CLAIM_STATUSES)
            pending_review_count = sum(1 for claim in claims if claim.review_status == "pending")
            numeric_checked = [claim for claim in claims if claim.numeric_check_status]
            numeric_failed_count = sum(1 for claim in numeric_checked if _is_failed_check(claim.numeric_check_status))
            numeric_pass_count = sum(1 for claim in numeric_checked if _is_pass_check(claim.numeric_check_status))
            citation_supported_count = sum(1 for claim in claims if claim.evidence_links or _is_pass_check(claim.citation_check_status))
            citation_failed_count = sum(1 for claim in claims if _is_failed_check(claim.citation_check_status))
            schema_checked_count = int(
                session.scalar(select(func.count(LLMRun.id)).where(LLMRun.schema_valid.is_not(None))) or 0
            )
            schema_valid_count = int(
                session.scalar(select(func.count(LLMRun.id)).where(LLMRun.schema_valid.is_(True))) or 0
            )
            llm_run_count = int(session.scalar(select(func.count(LLMRun.id))) or 0)
            llm_success_count = int(session.scalar(select(func.count(LLMRun.id)).where(LLMRun.status == "success")) or 0)
            llm_failed_count = int(session.scalar(select(func.count(LLMRun.id)).where(LLMRun.status != "success")) or 0)
            fallback_count = int(session.scalar(select(func.count(LLMRun.id)).where(LLMRun.fallback_used.is_(True))) or 0)
            llm_latency_values = [
                int(value)
                for value in session.scalars(select(LLMRun.latency_ms).where(LLMRun.latency_ms.is_not(None))).all()
                if isinstance(value, int)
            ]
            llm_cost = float(session.scalar(select(func.coalesce(func.sum(LLMRun.cost_usd), 0.0))) or 0.0)
            recent_llm_runs = list(
                session.scalars(select(LLMRun).order_by(LLMRun.created_at.desc(), LLMRun.id.desc()).limit(10)).all()
            )

            failure_counter = _build_failure_counter(
                tasks=active_tasks,
                claims=claims,
                llm_failed_count=llm_failed_count,
                fallback_count=fallback_count,
                schema_invalid_count=max(0, schema_checked_count - schema_valid_count),
                numeric_failed_count=numeric_failed_count,
                citation_failed_count=citation_failed_count,
                pending_review_count=pending_review_count,
                failed_claim_count=failed_claim_count,
            )

            metrics = {
                "active_task_count": active_task_count,
                "completed_task_count": completed_task_count,
                "delivery_pass_rate": _ratio(completed_task_count, active_task_count),
                "average_quality_score": round(sum(quality_scores) / len(quality_scores), 4) if quality_scores else None,
                "claim_count": claim_count,
                "traceable_claim_count": traceable_claim_count,
                "traceable_claim_rate": _ratio(traceable_claim_count, claim_count),
                "evidence_coverage_rate": _ratio(traceable_claim_count, claim_count),
                "verified_claim_count": verified_claim_count,
                "verified_claim_rate": _ratio(verified_claim_count, claim_count),
                "numeric_checked_count": len(numeric_checked),
                "numeric_pass_count": numeric_pass_count,
                "numeric_failed_count": numeric_failed_count,
                "numeric_consistency_rate": _ratio(len(numeric_checked) - numeric_failed_count, len(numeric_checked)),
                "citation_supported_count": citation_supported_count,
                "citation_failed_count": citation_failed_count,
                "citation_support_rate": _ratio(citation_supported_count, claim_count),
                "schema_checked_count": schema_checked_count,
                "schema_valid_count": schema_valid_count,
                "schema_valid_rate": _ratio(schema_valid_count, schema_checked_count),
                "llm_run_count": llm_run_count,
                "llm_success_count": llm_success_count,
                "llm_failed_count": llm_failed_count,
                "llm_success_rate": _ratio(llm_success_count, llm_run_count),
                "fallback_count": fallback_count,
                "average_llm_latency_ms": round(sum(llm_latency_values) / len(llm_latency_values), 2)
                if llm_latency_values
                else None,
                "llm_cost_usd": round(llm_cost, 6),
            }

            return {
                "metrics": metrics,
                "quality_gates": _quality_gates(metrics),
                "claim_quality": _claim_quality(metrics),
                "model_health": _model_health(metrics, recent_llm_runs),
                "failure_categories": _failure_categories(failure_counter),
                "recent_tasks": [_task_quality_row(task) for task in active_tasks[:limit]],
                "recent_llm_runs": [_llm_run_row(run) for run in recent_llm_runs],
                "notes": _notes(metrics),
            }

    def task_diagnostics(self, task_id: str) -> dict[str, Any]:
        """Return a task-scoped diagnosis that explains where the user should fix quality issues."""

        with self.session_factory() as session:
            task = session.scalar(
                select(ReportTask)
                .where(ReportTask.task_id == task_id)
                .options(selectinload(ReportTask.claims).selectinload(ReportClaim.evidence_links).selectinload(ClaimEvidence.evidence_item))
            )
            if task is None:
                raise ReportTaskNotFound(task_id)
            claims = list(task.claims or [])
            runs = list(
                session.scalars(
                    select(LLMRun)
                    .where(LLMRun.task_id == task_id)
                    .order_by(LLMRun.created_at.desc(), LLMRun.id.desc())
                    .limit(50)
                ).all()
            )

        quality_result = (task.metadata_json or {}).get("quality_result")
        quality_result = quality_result if isinstance(quality_result, dict) else {}
        delivery_gate = quality_result.get("delivery_gate") if isinstance(quality_result.get("delivery_gate"), dict) else {}
        quality_issues = _top_quality_issues(quality_result)
        issue_groups = _task_claim_issue_groups(claims)
        model_issues = _task_model_issues(runs)
        counters = {
            "claim_count": len(claims),
            "missing_evidence_count": len(issue_groups["missing_evidence"]),
            "unsupported_claim_count": len(issue_groups["unsupported_claims"]),
            "numeric_conflict_count": len(issue_groups["numeric_conflicts"]),
            "citation_gap_count": len(issue_groups["citation_gaps"]),
            "pending_review_count": len(issue_groups["pending_review"]),
            "model_issue_count": len(model_issues),
            "quality_issue_count": len(quality_issues),
        }
        blockers = _task_blockers(
            task=task,
            delivery_gate=delivery_gate,
            quality_issues=quality_issues,
            issue_groups=issue_groups,
            model_issues=model_issues,
        )
        return {
            "task": _task_diagnostic_header(task, delivery_gate),
            "summary": {
                **counters,
                "delivery_pass": delivery_gate.get("delivery_pass"),
                "quality_score": task.quality_score,
                "traceable_claim_rate": _ratio(
                    len(claims) - counters["missing_evidence_count"],
                    len(claims),
                ),
                "verified_claim_rate": _ratio(
                    sum(1 for claim in claims if claim.verification_status in VERIFIED_CLAIM_STATUSES),
                    len(claims),
                ),
            },
            "quality_gates": _task_quality_checks(task=task, delivery_gate=delivery_gate, counters=counters),
            "blockers": blockers,
            "claim_issues": {
                key: [_claim_issue_row(claim) for claim in values[:12]]
                for key, values in issue_groups.items()
            },
            "model_issues": model_issues,
            "recommended_actions": _task_recommended_actions(counters=counters, blockers=blockers),
            "quality_issues": [_quality_issue_row(item) for item in quality_issues[:10]],
        }


def _build_failure_counter(
    *,
    tasks: list[ReportTask],
    claims: list[ReportClaim],
    llm_failed_count: int,
    fallback_count: int,
    schema_invalid_count: int,
    numeric_failed_count: int,
    citation_failed_count: int,
    pending_review_count: int,
    failed_claim_count: int,
) -> Counter[str]:
    counter: Counter[str] = Counter()
    for task in tasks:
        if task.status == "quality_failed":
            counter["quality_gate_blocker"] += 1
        if task.status in {"failed", "timeout"}:
            counter["task_runtime_failure"] += 1
        quality_result = (task.metadata_json or {}).get("quality_result")
        if isinstance(quality_result, dict):
            for issue in _top_quality_issues(quality_result):
                category = str(issue.get("category") or issue.get("severity") or "quality_issue").strip()
                counter[category or "quality_issue"] += 1
    if failed_claim_count:
        counter["claim_not_supported"] += failed_claim_count
    if citation_failed_count:
        counter["citation_missing"] += citation_failed_count
    if numeric_failed_count:
        counter["numeric_mismatch"] += numeric_failed_count
    if pending_review_count:
        counter["pending_claim_review"] += pending_review_count
    missing_evidence = sum(1 for claim in claims if not claim.evidence_links)
    if missing_evidence:
        counter["evidence_gap"] += missing_evidence
    if llm_failed_count:
        counter["model_run_failure"] += llm_failed_count
    if schema_invalid_count:
        counter["schema_invalid"] += schema_invalid_count
    if fallback_count:
        counter["model_fallback"] += fallback_count
    return counter


def _top_quality_issues(quality_result: dict[str, Any]) -> list[dict[str, Any]]:
    raw = quality_result.get("top_quality_issues") or []
    if not isinstance(raw, list):
        return []
    issues: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            issues.append(item)
        elif isinstance(item, str):
            issues.append({"message": item, "category": "quality_issue", "severity": "warning"})
    return issues


def _quality_gates(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _gate("delivery_pass_rate", "交付通过率", metrics["delivery_pass_rate"], 0.8, "完成且通过质量门禁的研报任务占比。"),
        _gate("average_quality_score", "平均质量分", metrics["average_quality_score"], 0.8, "已评分研报的客观质量均值。"),
        _gate("traceable_claim_rate", "可追溯主张率", metrics["traceable_claim_rate"], 0.8, "绑定证据的主张占比。"),
        _gate("citation_support_rate", "引用支持率", metrics["citation_support_rate"], 0.8, "有引用支持或证据绑定的主张占比。"),
        _gate("numeric_consistency_rate", "数值一致性", metrics["numeric_consistency_rate"], 0.95, "已检查数字中未发现冲突的占比。"),
        _gate("schema_valid_rate", "结构化输出有效率", metrics["schema_valid_rate"], 0.95, "模型结构化输出通过校验的占比。"),
        _gate("llm_success_rate", "模型运行成功率", metrics["llm_success_rate"], 0.95, "智能体和校验链路的运行成功占比。"),
    ]


def _claim_quality(metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "total": metrics["claim_count"],
        "traceable": metrics["traceable_claim_count"],
        "verified": metrics["verified_claim_count"],
        "pending_review": metrics.get("claim_count", 0) - metrics["verified_claim_count"],
        "numeric_failed": metrics["numeric_failed_count"],
        "citation_failed": metrics["citation_failed_count"],
        "cards": [
            {"label": "证据覆盖", "value": metrics["evidence_coverage_rate"], "count": metrics["traceable_claim_count"]},
            {"label": "校验通过", "value": metrics["verified_claim_rate"], "count": metrics["verified_claim_count"]},
            {"label": "引用支持", "value": metrics["citation_support_rate"], "count": metrics["citation_supported_count"]},
            {"label": "数值一致", "value": metrics["numeric_consistency_rate"], "count": metrics["numeric_pass_count"]},
        ],
    }


def _model_health(metrics: dict[str, Any], runs: list[LLMRun]) -> dict[str, Any]:
    role_counter = Counter(str(run.model_role or run.prompt_key or "unknown") for run in runs)
    return {
        "run_count": metrics["llm_run_count"],
        "success_count": metrics["llm_success_count"],
        "failed_count": metrics["llm_failed_count"],
        "fallback_count": metrics["fallback_count"],
        "success_rate": metrics["llm_success_rate"],
        "schema_valid_rate": metrics["schema_valid_rate"],
        "average_latency_ms": metrics["average_llm_latency_ms"],
        "cost_usd": metrics["llm_cost_usd"],
        "recent_roles": [{"role": key, "count": value} for key, value in role_counter.most_common()],
    }


def _failure_categories(counter: Counter[str]) -> list[dict[str, Any]]:
    return [
        {
            "key": key,
            "label": _failure_label(key),
            "count": value,
            "severity": _failure_severity(key),
            "next_view": _failure_next_view(key),
        }
        for key, value in counter.most_common(10)
    ]


def _task_quality_row(task: ReportTask) -> dict[str, Any]:
    claims = list(task.claims or [])
    claim_count = len(claims)
    traceable = sum(1 for claim in claims if claim.evidence_links)
    verified = sum(1 for claim in claims if claim.verification_status in VERIFIED_CLAIM_STATUSES)
    citation_failed = sum(1 for claim in claims if _is_failed_check(claim.citation_check_status))
    numeric_failed = sum(1 for claim in claims if _is_failed_check(claim.numeric_check_status))
    pending_review = sum(1 for claim in claims if claim.review_status == "pending")
    quality_result = (task.metadata_json or {}).get("quality_result")
    delivery_pass = None
    issue_count = 0
    if isinstance(quality_result, dict):
        delivery_gate = quality_result.get("delivery_gate") if isinstance(quality_result.get("delivery_gate"), dict) else {}
        delivery_pass = delivery_gate.get("delivery_pass")
        issue_count = len(_top_quality_issues(quality_result))
    return {
        "task_id": task.task_id,
        "symbol": task.symbol,
        "company_name": (task.metadata_json or {}).get("company_name") or task.symbol,
        "period": task.period,
        "report_type": task.report_type,
        "status": task.status,
        "quality_score": task.quality_score,
        "delivery_pass": delivery_pass,
        "issue_count": issue_count,
        "claim_count": claim_count,
        "traceable_claim_rate": _ratio(traceable, claim_count),
        "verified_claim_rate": _ratio(verified, claim_count),
        "citation_failed_count": citation_failed,
        "numeric_failed_count": numeric_failed,
        "pending_review_count": pending_review,
        "updated_at": _dt(task.finished_at or task.started_at or task.created_at),
    }


def _llm_run_row(run: LLMRun) -> dict[str, Any]:
    return {
        "run_id": run.run_id,
        "task_id": run.task_id,
        "label": _run_label(run),
        "status": run.status,
        "schema_valid": run.schema_valid,
        "fallback_used": run.fallback_used,
        "latency_ms": run.latency_ms,
        "cost_usd": run.cost_usd,
        "created_at": _dt(run.created_at),
    }


def _notes(metrics: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    if metrics["active_task_count"] == 0:
        notes.append("暂无研报任务，创建任务后会生成交付通过率和质量分。")
    if metrics["claim_count"] == 0:
        notes.append("暂无主张数据，导入报告产物或完成研报任务后会展示主张级质量。")
    if metrics["llm_run_count"] == 0:
        notes.append("暂无模型运行记录，PromptOps 和质量门禁接入后会展示结构化输出有效率。")
    return notes


def _task_diagnostic_header(task: ReportTask, delivery_gate: dict[str, Any]) -> dict[str, Any]:
    metadata = task.metadata_json or {}
    return {
        "task_id": task.task_id,
        "symbol": task.symbol,
        "company_name": metadata.get("company_name") or task.symbol,
        "period": task.period,
        "report_type": task.report_type,
        "status": task.status,
        "quality_score": task.quality_score,
        "delivery_pass": delivery_gate.get("delivery_pass"),
        "updated_at": _dt(task.finished_at or task.started_at or task.created_at),
    }


def _task_claim_issue_groups(claims: list[ReportClaim]) -> dict[str, list[ReportClaim]]:
    return {
        "missing_evidence": [claim for claim in claims if not claim.evidence_links],
        "unsupported_claims": [
            claim for claim in claims if claim.verification_status in FAILED_CLAIM_STATUSES
        ],
        "numeric_conflicts": [claim for claim in claims if _is_failed_check(claim.numeric_check_status)],
        "citation_gaps": [claim for claim in claims if _is_failed_check(claim.citation_check_status) or not claim.evidence_links],
        "pending_review": [claim for claim in claims if claim.review_status == "pending"],
    }


def _task_model_issues(runs: list[LLMRun]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for run in runs:
        if run.status == "success" and run.schema_valid is not False and not run.fallback_used:
            continue
        if run.status != "success":
            severity = "high"
            reason = "模型运行失败"
        elif run.schema_valid is False:
            severity = "high"
            reason = "结构化输出未通过校验"
        else:
            severity = "medium"
            reason = "模型降级运行"
        issues.append(
            {
                "run_id": run.run_id,
                "label": _run_label(run),
                "status": run.status,
                "reason": reason,
                "severity": severity,
                "schema_valid": run.schema_valid,
                "fallback_used": run.fallback_used,
                "latency_ms": run.latency_ms,
                "error_message": run.error_message,
                "created_at": _dt(run.created_at),
                "next_view": "promptops",
            }
        )
    return issues[:12]


def _task_blockers(
    *,
    task: ReportTask,
    delivery_gate: dict[str, Any],
    quality_issues: list[dict[str, Any]],
    issue_groups: dict[str, list[ReportClaim]],
    model_issues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if delivery_gate.get("delivery_pass") is False or task.status == "quality_failed":
        blockers.append(
            {
                "key": "quality_gate_blocker",
                "label": "质量门禁未通过",
                "severity": "high",
                "count": 1,
                "description": "当前研报未达到正式交付条件，需要先处理下方主张、引用、数字或模型运行问题。",
                "next_view": "tasks",
            }
        )
    for key, label, description, next_view in [
        ("missing_evidence", "证据链缺口", "部分主张没有绑定证据，正式报告可信度不足。", "claims"),
        ("unsupported_claims", "主张未获支持", "部分主张未通过校验，需要补证据、改写或驳回。", "claims"),
        ("numeric_conflicts", "数字不一致", "财务数字存在冲突，需要回到财务事实和原文证据修正。", "facts"),
        ("citation_gaps", "引用缺失", "引用无法支撑主张，需补充来源或降低表述强度。", "claims"),
        ("pending_review", "待人工复核", "仍有主张等待人工确认，正式导出前需要处理。", "claims"),
    ]:
        count = len(issue_groups.get(key) or [])
        if count:
            blockers.append(
                {
                    "key": key,
                    "label": label,
                    "severity": "high" if key in {"unsupported_claims", "numeric_conflicts", "citation_gaps"} else "medium",
                    "count": count,
                    "description": description,
                    "next_view": next_view,
                }
            )
    if model_issues:
        blockers.append(
            {
                "key": "model_issues",
                "label": "模型运行问题",
                "severity": "high" if any(item["severity"] == "high" for item in model_issues) else "medium",
                "count": len(model_issues),
                "description": "智能体调用存在失败、结构化输出无效或降级运行，需要到提示词运营查看调用细节。",
                "next_view": "promptops",
            }
        )
    for issue in quality_issues:
        category = str(issue.get("category") or "quality_issue")
        if any(item["key"] == category for item in blockers):
            continue
        blockers.append(
            {
                "key": category,
                "label": _failure_label(category),
                "severity": _failure_severity(category),
                "count": 1,
                "description": str(issue.get("message") or "质量检查发现问题。"),
                "next_view": _failure_next_view(category),
            }
        )
    return blockers[:12]


def _task_quality_checks(*, task: ReportTask, delivery_gate: dict[str, Any], counters: dict[str, int]) -> list[dict[str, Any]]:
    return [
        _task_check(
            "delivery_gate",
            "交付门禁",
            delivery_gate.get("delivery_pass"),
            "报告是否达到正式交付条件。",
        ),
        _task_check(
            "evidence_binding",
            "证据绑定",
            counters["missing_evidence_count"] == 0,
            "每条关键主张都需要绑定可追溯证据。",
            value=counters["missing_evidence_count"],
        ),
        _task_check(
            "claim_verification",
            "主张校验",
            counters["unsupported_claim_count"] == 0,
            "主张需要通过证据、数字和引用校验。",
            value=counters["unsupported_claim_count"],
        ),
        _task_check(
            "numeric_consistency",
            "数字一致性",
            counters["numeric_conflict_count"] == 0,
            "研报中的财务数字不能与事实库或原文证据冲突。",
            value=counters["numeric_conflict_count"],
        ),
        _task_check(
            "citation_support",
            "引用支持",
            counters["citation_gap_count"] == 0,
            "引用应能支撑对应主张。",
            value=counters["citation_gap_count"],
        ),
        _task_check(
            "model_health",
            "模型运行",
            counters["model_issue_count"] == 0,
            "智能体调用和结构化输出应稳定可追踪。",
            value=counters["model_issue_count"],
        ),
    ]


def _task_check(key: str, label: str, passed: bool | None, description: str, *, value: Any = None) -> dict[str, Any]:
    status = "pending" if passed is None else ("passed" if passed else "failed")
    return {"key": key, "label": label, "passed": passed, "status": status, "value": value, "description": description}


def _claim_issue_row(claim: ReportClaim) -> dict[str, Any]:
    evidence_count = len(claim.evidence_links or [])
    return {
        "id": claim.id,
        "task_id": claim.task_id,
        "section_name": claim.section_name,
        "claim_type": claim.claim_type,
        "claim_text": claim.claim_text,
        "review_status": claim.review_status,
        "verification_status": claim.verification_status,
        "numeric_check_status": claim.numeric_check_status,
        "citation_check_status": claim.citation_check_status,
        "evidence_count": evidence_count,
        "evidence_titles": [
            link.evidence_item.title or link.evidence_item.evidence_id
            for link in claim.evidence_links[:3]
            if link.evidence_item is not None
        ],
    }


def _task_recommended_actions(*, counters: dict[str, int], blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if counters["pending_review_count"] or counters["unsupported_claim_count"] or counters["citation_gap_count"]:
        actions.append(
            {
                "label": "进入主张复核",
                "view": "claims",
                "reason": "处理待复核、未获支持和引用缺失的主张。",
                "priority": "high",
            }
        )
    if counters["numeric_conflict_count"]:
        actions.append(
            {
                "label": "核对财务事实",
                "view": "facts",
                "reason": "修正数字冲突或补充原始财务事实来源。",
                "priority": "high",
            }
        )
    if counters["missing_evidence_count"]:
        actions.append(
            {
                "label": "补充证据",
                "view": "evidence",
                "reason": "为无证据主张补充官方公告、年报或一手来源。",
                "priority": "medium",
            }
        )
    if counters["model_issue_count"]:
        actions.append(
            {
                "label": "查看模型调用",
                "view": "promptops",
                "reason": "定位模型失败、结构化输出无效或降级运行。",
                "priority": "medium",
            }
        )
    if not actions and not blockers:
        actions.append(
            {
                "label": "查看导出状态",
                "view": "export",
                "reason": "当前未发现明显质量阻塞，可检查正式导出条件。",
                "priority": "low",
            }
        )
    return actions


def _quality_issue_row(issue: dict[str, Any]) -> dict[str, Any]:
    category = str(issue.get("category") or "quality_issue")
    severity = str(issue.get("severity") or _failure_severity(category))
    return {
        "category": category,
        "label": _failure_label(category),
        "severity": severity,
        "message": str(issue.get("message") or issue.get("detail") or issue.get("reason") or "质量检查发现问题。"),
        "next_view": _failure_next_view(category),
    }


def _gate(key: str, label: str, value: float | None, target: float, description: str) -> dict[str, Any]:
    if value is None:
        status = "pending"
    elif value >= target:
        status = "passed"
    elif value >= target * 0.75:
        status = "warning"
    else:
        status = "failed"
    return {"key": key, "label": label, "value": value, "target": target, "status": status, "description": description}


def _failure_label(key: str) -> str:
    mapping = {
        "quality_gate_blocker": "质量门禁阻塞",
        "task_runtime_failure": "任务运行失败",
        "claim_not_supported": "主张未获证据支持",
        "citation_missing": "引用缺失或不支持",
        "numeric_mismatch": "数字不一致",
        "pending_claim_review": "待人工复核",
        "evidence_gap": "证据链缺口",
        "model_run_failure": "模型运行失败",
        "schema_invalid": "结构化输出无效",
        "model_fallback": "模型降级运行",
        "citation_or_evidence_gap": "引用或证据缺口",
        "source_access_or_fetch": "来源访问失败",
        "chart_text_mismatch": "图表文字不一致",
        "valuation": "估值口径问题",
        "period": "期间错配",
        "numeric": "数字核验问题",
        "structure": "结构完整性问题",
        "freshness": "时效性问题",
        "quality_issue": "质量问题",
    }
    return mapping.get(key, key)


def _failure_severity(key: str) -> str:
    if key in {"quality_gate_blocker", "task_runtime_failure", "claim_not_supported", "citation_missing", "numeric_mismatch", "schema_invalid", "model_run_failure"}:
        return "high"
    if key in {"pending_claim_review", "evidence_gap", "model_fallback"}:
        return "medium"
    return "low"


def _failure_next_view(key: str) -> str:
    if key in {"claim_not_supported", "citation_missing", "numeric_mismatch", "pending_claim_review", "evidence_gap"}:
        return "claims"
    if key in {"model_run_failure", "schema_invalid", "model_fallback"}:
        return "promptops"
    if key in {"task_runtime_failure", "quality_gate_blocker"}:
        return "tasks"
    return "evaluation"


def _run_label(run: LLMRun) -> str:
    mapping = {
        "quality_gate": "质量门禁",
        "verifier": "校验智能体",
        "writer": "研报撰写",
        "researcher": "资料检索",
        "planner": "任务规划",
        "final_answer": "最终研报",
    }
    role = str(run.model_role or "").strip()
    if role in mapping:
        return mapping[role]
    prompt_key = str(run.prompt_key or "").strip()
    prompt_mapping = {
        "report_quality_gate": "质量门禁",
        "claim_verifier": "主张校验",
    }
    return prompt_mapping.get(prompt_key, prompt_key or "模型运行")


def _is_pass_check(value: str | None) -> bool:
    return str(value or "").strip().lower() in PASS_CHECK_STATUSES


def _is_failed_check(value: str | None) -> bool:
    return str(value or "").strip().lower() in FAIL_CHECK_STATUSES


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _dt(value: Any) -> str | None:
    return value.isoformat() if value else None
