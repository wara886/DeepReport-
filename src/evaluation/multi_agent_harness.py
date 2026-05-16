"""Evaluation harness for the dynamic multi-agent report path."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from src.agents.multi_agent_orchestrator import MultiAgentOrchestrator
from src.evaluation.eval_v1 import EvalCase, load_eval_cases
from src.evaluation.numeric_audit import run_numeric_audit_for_case, summarize_numeric_audit
from src.models import ModelAdapter
from src.search import SearchManager
from src.utils.config import load_config


DEFAULT_REQUIRED_HEADERS = [
    "## 执行摘要",
    "## 业务概览",
    "## 股权结构与公司治理",
    "## 战略与主营业务",
    "## 三表摘要",
    "## 财务分析",
    "## 估值观察",
    "## 估值敏感性",
    "## 风险评估",
    "## 投资结论",
    "## 参考来源",
    "## 合规披露与风险提示",
]

CONTEST_CHECKLIST_ITEMS = [
    ("structure", "章节结构覆盖", 15),
    ("company_depth", "公司研报深度", 20),
    ("evidence", "证据绑定与引用", 20),
    ("numeric", "数值一致性", 15),
    ("verification", "验证闭环", 15),
    ("charts", "图表一致性", 10),
    ("retrieval", "检索诊断", 5),
]


def run_multi_agent_evaluation(
    config_path: str = "configs/evaluation_stage12a.yaml",
    output_root: str | Path | None = None,
    eval_case_path: str | Path | None = None,
    max_samples: int | None = None,
    model: ModelAdapter | None = None,
    search_manager: SearchManager | None = None,
) -> Dict[str, Any]:
    """Run eval_v1 cases through MultiAgentOrchestrator and write harness outputs."""

    cfg = load_config(config_path)
    eval_cfg = dict(cfg.get("evaluation", {}))
    ma_cfg = dict(eval_cfg.get("multi_agent", {}))
    raw_data_root = str(eval_cfg.get("raw_root", "data/raw/real_data"))
    out_root = Path(output_root or ma_cfg.get("output_root") or "data/evaluation/multi_agent")
    case_path = Path(eval_case_path or eval_cfg.get("eval_case_path") or "data/eval_v1/cases.jsonl")
    model_config_path = str(ma_cfg.get("model_config_path") or "configs/model_backends.yaml")
    sample_count = int(max_samples if max_samples is not None else ma_cfg.get("max_samples", eval_cfg.get("max_samples", 5)))
    variants = _variants(ma_cfg)
    required_headers = list(ma_cfg.get("required_headers") or DEFAULT_REQUIRED_HEADERS)

    cases = load_eval_cases(case_path)[:sample_count]
    if not cases:
        raise ValueError(f"No eval cases found: {case_path}")

    out_root.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, Any]] = []
    numeric_rows: List[Dict[str, Any]] = []
    for case in cases:
        for variant in variants:
            row = _run_case_variant(
                case=case,
                variant=variant,
                output_root=out_root,
                raw_data_root=raw_data_root,
                required_headers=required_headers,
                model_config_path=model_config_path,
                model=model,
                search_manager=search_manager,
            )
            rows.append(row)
            report_json_path = Path(str(row["artifacts"]["report_json"]))
            if report_json_path.exists():
                report_json = dict(_read_json(report_json_path))
                audit = run_numeric_audit_for_case(case=case.to_dict(), report_claims=list(report_json.get("claims", [])))
                audit["variant_id"] = row["variant_id"]
                audit["task_type"] = row["task_type"]
                numeric_rows.append(audit)

    summary = _summarize(rows=rows, numeric_rows=numeric_rows, output_root=out_root, config_path=config_path, eval_case_path=case_path)
    _write_jsonl(out_root / "per_report_metrics.jsonl", rows)
    _write_jsonl(out_root / "per_case_numeric_audit_v1.jsonl", numeric_rows)
    (out_root / "numeric_audit_v1_summary.json").write_text(
        json.dumps(summarize_numeric_audit(numeric_rows), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_root / "evaluation_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_root / "summary.md").write_text(_render_summary_md(summary), encoding="utf-8")
    return summary


def _run_case_variant(
    case: EvalCase,
    variant: Dict[str, Any],
    output_root: Path,
    raw_data_root: str,
    required_headers: List[str],
    model_config_path: str,
    model: ModelAdapter | None,
    search_manager: SearchManager | None,
) -> Dict[str, Any]:
    variant_id = str(variant.get("id") or "dynamic_fast")
    case_root = output_root / "runs" / case.case_id / variant_id
    outputs = case_root / "outputs"
    reports = case_root / "reports"
    orchestrator = MultiAgentOrchestrator(
        output_dir=str(outputs),
        report_dir=str(reports),
        config_path=model_config_path,
        raw_data_root=raw_data_root,
        model=model,
        search_manager=search_manager,
        memory_enabled=bool(variant.get("memory_enabled", False)),
        memory_root=str(variant.get("memory_root", case_root / "memory")),
    )
    orchestrator.run(
        research_topic=case.query,
        symbol=case.symbol,
        period=case.period,
        execution_mode=str(variant.get("execution_mode", "dynamic")),
        fast=bool(variant.get("fast", True)),
        search_engines=list(variant.get("engines", ["local_real_data", "local_evidence"])),
        retrieval_ranking_mode=str(variant.get("retrieval_ranking_mode", "hybrid_rerank")),
    )

    claims = _read_list(outputs / "claims.json")
    evidence_records = _read_list(outputs / "evidence.json")
    verification = _read_dict(outputs / "verification_report.json")
    search_meta = _read_dict(outputs / "search_meta.json")
    run_summary = _read_dict(outputs / "run_summary.json")
    task_trace = _read_jsonl(outputs / "task_trace.jsonl")
    task_route_context = _read_dict(outputs / "task_route_context.json")
    skill_metrics = _skill_routing_metrics(task_trace=task_trace, task_route_context=task_route_context)
    durable_memory_artifacts = run_summary.get("durable_memory", {})
    if not isinstance(durable_memory_artifacts, dict):
        durable_memory_artifacts = {}
    chart_consistency = _read_dict(outputs / "chart_consistency.json")
    markdown = (reports / "report.md").read_text(encoding="utf-8") if (reports / "report.md").exists() else ""
    evidence_ids = {str(item.get("evidence_id") or item.get("sample_id") or "") for item in evidence_records if isinstance(item, dict)}
    claim_count = len(claims)
    claims_with_evidence = [
        claim for claim in claims if isinstance(claim, dict) and isinstance(claim.get("evidence_ids"), list) and claim.get("evidence_ids")
    ]
    aligned_ids = [
        evidence_id
        for claim in claims_with_evidence
        for evidence_id in claim.get("evidence_ids", [])
        if str(evidence_id) in evidence_ids
    ]
    all_claim_eids = [evidence_id for claim in claims_with_evidence for evidence_id in claim.get("evidence_ids", [])]

    engine_meta = dict(search_meta.get("engine_meta", {})) if isinstance(search_meta.get("engine_meta"), dict) else {}
    local_meta = dict(engine_meta.get("local_evidence", {})) if isinstance(engine_meta.get("local_evidence"), dict) else {}
    search_hits = _read_list(outputs / "evidence.json")
    contest = _contest_checklist(
        markdown=markdown,
        claims=claims,
        evidence_records=evidence_records,
        verification=verification,
        chart_consistency=chart_consistency,
        local_meta=local_meta,
        required_headers=required_headers,
    )
    failure_taxonomy = _failure_taxonomy(
        contest=contest,
        verification=verification,
        local_meta=local_meta,
        chart_consistency=chart_consistency,
    )
    unsupported_fallback_count = _unsupported_fallback_count(failure_taxonomy=failure_taxonomy, engine_meta=engine_meta, task_trace=task_trace)

    return {
        "case_id": case.case_id,
        "sample_id": f"{case.symbol}:{case.period}",
        "symbol": case.symbol,
        "period": case.period,
        "query": case.query,
        "task_type": case.task_type,
        "variant_id": variant_id,
        "memory_enabled": bool(variant.get("memory_enabled", False)),
        "durable_memory_enabled": bool(run_summary.get("durable_memory_enabled", False)),
        "durable_memory_available": bool(durable_memory_artifacts.get("working_snapshot")),
        "durable_memory_artifact": str(durable_memory_artifacts.get("working_snapshot", "")),
        "writer_mode": "multi_agent",
        "writer_backend": "final_answer_agent",
        "ranking_mode": str(variant.get("retrieval_ranking_mode", "hybrid_rerank")),
        "structure_completeness": _structure_completeness(markdown, required_headers),
        "numeric_consistency": _numeric_consistency(claims),
        "evidence_alignment": round(float(len(aligned_ids)) / float(len(all_claim_eids)), 4) if all_claim_eids else 0.0,
        "evidence_coverage": round(float(len(claims_with_evidence)) / float(claim_count), 4) if claim_count else 0.0,
        "claim_count": claim_count,
        "report_char_count": len(markdown),
        "rule_verifier_passed": bool(verification.get("passed", False)),
        "verification_pass_rate": 1.0 if bool(verification.get("passed", False)) else 0.0,
        "rule_verifier_error_count": len(verification.get("errors", [])) if isinstance(verification.get("errors"), list) else 0,
        "current_verifier_pass_ratio": 1.0 if bool(verification.get("passed", False)) else 0.0,
        "current_verifier_checkpoint_used": False,
        "writer_fallback_triggered": False,
        "writer_backend_mode": "multi_agent",
        "writer_error_message": "",
        "retrieval_mode_resolved": str(local_meta.get("mode", variant.get("retrieval_ranking_mode", ""))),
        "retrieval_fallback_used": bool(local_meta.get("fallback_used", False)),
        "retrieved_doc_count": len(search_hits),
        "retrieval_failure_reason": str(local_meta.get("failure_reason", "")),
        "reranked_topk_ids": [str(item.get("evidence_id") or item.get("sample_id") or "") for item in search_hits],
        "reranked_topk_source_types": [str(item.get("source_type") or "") for item in search_hits],
        "chart_consistency_passed": bool(chart_consistency.get("passed", False)),
        "contest_checklist_score": contest["score"],
        "contest_checklist_max_score": contest["max_score"],
        "contest_checklist_pass_rate": contest["pass_rate"],
        "contest_checklist": contest,
        "failure_taxonomy": failure_taxonomy,
        "unsupported_fallback_count": unsupported_fallback_count,
        "unsupported_fallback_triggered": unsupported_fallback_count > 0,
        "numeric_audit_pass_rate": _numeric_consistency(claims),
        "citation_support_rate": round(
            (float(len(claims_with_evidence)) / float(claim_count) if claim_count else 0.0)
            * (float(len(aligned_ids)) / float(len(all_claim_eids)) if all_claim_eids else 0.0),
            4,
        ),
        **skill_metrics,
        "revision_rounds": int(run_summary.get("revision_rounds", 0) or 0),
        "total_duration_sec": float(run_summary.get("total_duration_sec", 0.0) or 0.0),
        "artifacts": {
            "claim_table": str(outputs / "claims.json"),
            "verification_report": str(outputs / "verification_report.json"),
            "chart_metadata": str(outputs / "charts.json"),
            "chart_consistency": str(outputs / "chart_consistency.json"),
            "report_md": str(reports / "report.md"),
            "report_html": str(reports / "report.html"),
            "report_json": str(reports / "report.json"),
            "task_trace": str(outputs / "task_trace.jsonl"),
            "search_meta": str(outputs / "search_meta.json"),
            "task_route_context": str(outputs / "task_route_context.json"),
        },
    }


def _variants(ma_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = ma_cfg.get("variants")
    if isinstance(raw, list) and raw:
        return [dict(item) for item in raw if isinstance(item, dict)]
    return [
        {
            "id": "dynamic_fast",
            "execution_mode": "dynamic",
            "fast": True,
            "engines": ["local_real_data", "local_evidence"],
            "retrieval_ranking_mode": "hybrid_rerank",
        }
    ]


def _summarize(rows: List[Dict[str, Any]], numeric_rows: List[Dict[str, Any]], output_root: Path, config_path: str, eval_case_path: Path) -> Dict[str, Any]:
    numeric_summary = summarize_numeric_audit(numeric_rows)
    taxonomy = _failure_taxonomy_summary(rows)
    return {
        "report_name": "multi_agent_regression",
        "sample_count": len({str(row.get("case_id")) for row in rows}),
        "report_count": len(rows),
        "variant_count": len({str(row.get("variant_id")) for row in rows}),
        "evidence_coverage": _mean(row.get("evidence_coverage", 0.0) for row in rows),
        "claim_grounded_rate": _mean(row.get("current_verifier_pass_ratio", 0.0) for row in rows),
        "verification_pass_rate": _mean(row.get("verification_pass_rate", 0.0) for row in rows),
        "unsupported_fallback_rate": _mean(1.0 if row.get("unsupported_fallback_triggered") else 0.0 for row in rows),
        "skill_routed_task_rate": _mean(row.get("skill_routed_task_rate", 0.0) for row in rows),
        "citation_support_rate": _mean(row.get("citation_support_rate", 0.0) for row in rows),
        "numeric_audit_pass_rate": _mean(row.get("numeric_audit_pass_rate", 0.0) for row in rows),
        "skill_selection_counts": _skill_selection_counts(rows),
        "numeric_accuracy": numeric_summary.get("numeric_accuracy", 0.0),
        "chart_consistency_pass_rate": _mean(1.0 if row.get("chart_consistency_passed") else 0.0 for row in rows),
        "revision_rate": _mean(1.0 if int(row.get("revision_rounds", 0) or 0) > 0 else 0.0 for row in rows),
        "avg_duration_sec": _mean(row.get("total_duration_sec", 0.0) for row in rows),
        "contest_checklist_score_mean": _mean(row.get("contest_checklist_score", 0.0) for row in rows),
        "contest_checklist_pass_rate_mean": _mean(row.get("contest_checklist_pass_rate", 0.0) for row in rows),
        "failure_taxonomy_summary": taxonomy,
        "regression_topics": _regression_topics(),
        "retrieval_ablation": _retrieval_ablation(rows),
        "numeric_audit": numeric_summary,
        "sources": {"config_path": str(config_path), "eval_case_path": str(eval_case_path)},
        "outputs": {
            "evaluation_summary_json": str(output_root / "evaluation_summary.json"),
            "summary_md": str(output_root / "summary.md"),
            "per_report_metrics_jsonl": str(output_root / "per_report_metrics.jsonl"),
            "numeric_audit_v1_summary_json": str(output_root / "numeric_audit_v1_summary.json"),
            "per_case_numeric_audit_v1_jsonl": str(output_root / "per_case_numeric_audit_v1.jsonl"),
        },
    }


def _retrieval_ablation(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_mode: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        mode = str(row.get("ranking_mode") or row.get("retrieval_mode_resolved") or "unknown")
        by_mode.setdefault(mode, []).append(row)

    modes: Dict[str, Dict[str, Any]] = {}
    for mode, items in sorted(by_mode.items()):
        modes[mode] = {
            "report_count": len(items),
            "evidence_alignment_mean": _mean(item.get("evidence_alignment", 0.0) for item in items),
            "evidence_coverage_mean": _mean(item.get("evidence_coverage", 0.0) for item in items),
            "verifier_pass_rate": _mean(1.0 if item.get("rule_verifier_passed") else 0.0 for item in items),
            "retrieval_fallback_rate": _mean(1.0 if item.get("retrieval_fallback_used") else 0.0 for item in items),
            "retrieved_doc_count_mean": _mean(item.get("retrieved_doc_count", 0.0) for item in items),
        }

    comparisons: Dict[str, Dict[str, Any]] = {}
    baseline = modes.get("bm25")
    for mode, metrics in modes.items():
        if mode == "bm25" or not baseline:
            continue
        comparisons[f"bm25_vs_{mode}"] = {
            "evidence_alignment_delta": round(
                float(metrics.get("evidence_alignment_mean", 0.0)) - float(baseline.get("evidence_alignment_mean", 0.0)),
                4,
            ),
            "evidence_coverage_delta": round(
                float(metrics.get("evidence_coverage_mean", 0.0)) - float(baseline.get("evidence_coverage_mean", 0.0)),
                4,
            ),
            "verifier_pass_delta": round(
                float(metrics.get("verifier_pass_rate", 0.0)) - float(baseline.get("verifier_pass_rate", 0.0)),
                4,
            ),
        }
    return {"modes": modes, "comparisons": comparisons}


def _contest_checklist(
    markdown: str,
    claims: List[Dict[str, Any]],
    evidence_records: List[Dict[str, Any]],
    verification: Dict[str, Any],
    chart_consistency: Dict[str, Any],
    local_meta: Dict[str, Any],
    required_headers: List[str],
) -> Dict[str, Any]:
    claim_sections = {str(claim.get("section_name", "")) for claim in claims if isinstance(claim, dict)}
    evidence_ids = {str(item.get("evidence_id") or item.get("sample_id") or "") for item in evidence_records if isinstance(item, dict)}
    claims_with_evidence = [
        claim for claim in claims if isinstance(claim, dict) and isinstance(claim.get("evidence_ids"), list) and claim.get("evidence_ids")
    ]
    all_claim_eids = [str(eid) for claim in claims_with_evidence for eid in claim.get("evidence_ids", [])]
    aligned = [eid for eid in all_claim_eids if eid in evidence_ids]
    evidence_alignment = float(len(aligned)) / float(len(all_claim_eids)) if all_claim_eids else 0.0
    numeric_score = _numeric_consistency(claims)
    section_score = _structure_completeness(markdown, required_headers)
    depth_sections = {
        "ownership_governance",
        "strategy_business",
        "financial_statements",
        "peer_compare",
        "valuation",
        "valuation_sensitivity",
        "risks",
    }
    depth_coverage = len(depth_sections & claim_sections) / float(len(depth_sections))

    item_scores = {
        "structure": section_score,
        "company_depth": depth_coverage,
        "evidence": evidence_alignment,
        "numeric": numeric_score,
        "verification": 1.0 if verification.get("passed", False) else 0.0,
        "charts": 1.0 if chart_consistency.get("passed", False) else 0.0,
        "retrieval": 0.0 if local_meta.get("failure_reason") else 1.0,
    }
    rows = []
    score = 0.0
    max_score = 0.0
    for key, label, weight in CONTEST_CHECKLIST_ITEMS:
        ratio = max(0.0, min(float(item_scores.get(key, 0.0)), 1.0))
        points = round(ratio * weight, 4)
        rows.append({"id": key, "label": label, "weight": weight, "ratio": round(ratio, 4), "points": points})
        score += points
        max_score += weight
    return {
        "score": round(score, 4),
        "max_score": int(max_score),
        "pass_rate": round(score / max_score, 4) if max_score else 0.0,
        "items": rows,
    }


def _failure_taxonomy(
    contest: Dict[str, Any],
    verification: Dict[str, Any],
    local_meta: Dict[str, Any],
    chart_consistency: Dict[str, Any],
) -> List[str]:
    failures: List[str] = []
    item_map = {str(item.get("id")): float(item.get("ratio", 0.0) or 0.0) for item in contest.get("items", []) if isinstance(item, dict)}
    if item_map.get("structure", 1.0) < 1.0:
        failures.append("section_missing")
    if item_map.get("company_depth", 1.0) < 1.0:
        failures.append("company_depth_incomplete")
    if item_map.get("evidence", 1.0) < 1.0:
        failures.append("evidence_alignment_gap")
    if item_map.get("numeric", 1.0) < 1.0:
        failures.append("numeric_inconsistency")
    if not verification.get("passed", False):
        errors = " ".join(str(item) for item in verification.get("errors", []) if item)
        if "Target symbol mismatch" in errors:
            failures.append("entity_mismatch")
        else:
            failures.append("verifier_failed")
    if local_meta.get("failure_reason"):
        failures.append(f"retrieval:{local_meta.get('failure_reason')}")
    if chart_consistency and not chart_consistency.get("passed", False):
        failures.append("chart_inconsistency")
    return sorted(set(failures)) or ["none"]


def _failure_taxonomy_summary(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows:
        taxonomy = row.get("failure_taxonomy", [])
        if isinstance(taxonomy, list):
            counter.update(str(item) for item in taxonomy)
        elif taxonomy:
            counter.update([str(taxonomy)])
    return dict(sorted(counter.items()))


def _skill_routing_metrics(task_trace: List[Dict[str, Any]], task_route_context: Dict[str, Any]) -> Dict[str, Any]:
    selected_names: List[str] = []
    routed_tasks = 0
    total_tasks = 0
    for item in task_trace:
        task = item.get("task") if isinstance(item.get("task"), dict) else item
        metadata = task.get("metadata", {}) if isinstance(task, dict) and isinstance(task.get("metadata"), dict) else {}
        selected = metadata.get("selected_skills", [])
        if not isinstance(selected, list):
            selected = []
        total_tasks += 1
        if selected:
            routed_tasks += 1
            selected_names.extend(str(name) for name in selected)

    if not selected_names and isinstance(task_route_context.get("tasks"), list):
        for item in task_route_context["tasks"]:
            if not isinstance(item, dict):
                continue
            selected = item.get("selected_skills", [])
            if isinstance(selected, list):
                selected_names.extend(str(name) for name in selected)

    return {
        "skill_registry_enabled": bool(task_route_context.get("skill_registry_enabled", selected_names)),
        "selected_skill_count": len(selected_names),
        "selected_skill_names": sorted(set(selected_names)),
        "tasks_with_selected_skills": routed_tasks,
        "task_trace_count": total_tasks,
        "skill_routed_task_rate": round(float(routed_tasks) / float(total_tasks), 4) if total_tasks else 0.0,
    }


def _unsupported_fallback_count(
    failure_taxonomy: List[str],
    engine_meta: Dict[str, Any],
    task_trace: List[Dict[str, Any]],
) -> int:
    count = sum(1 for item in failure_taxonomy if "unsupported" in str(item).lower() or "fallback" in str(item).lower())
    for meta in engine_meta.values():
        if isinstance(meta, dict):
            text = json.dumps(meta, ensure_ascii=False).lower()
            if "unsupported" in text or "fallback" in text:
                count += 1
    for item in task_trace:
        text = json.dumps(item, ensure_ascii=False).lower()
        if "unsupported dynamic task_type" in text:
            count += 1
    return count


def _skill_selection_counts(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows:
        names = row.get("selected_skill_names", [])
        if isinstance(names, list):
            counter.update(str(name) for name in names)
    return dict(sorted(counter.items()))


def _regression_topics() -> List[Dict[str, str]]:
    return [
        {"id": "entity_mismatch", "description": "ticker/公司名混淆，例如 Nvda 不应解析成 NADA。"},
        {"id": "evidence_gap", "description": "claim 缺少 evidence_id 或引用了不存在的证据。"},
        {"id": "chart_text_mismatch", "description": "图表来源、数值和正文 claim 不一致。"},
        {"id": "numeric_error", "description": "收入、利润率、现金流等数值与证据不匹配。"},
        {"id": "section_missing", "description": "赛题要求章节缺失，例如三表、治理、战略、估值敏感性。"},
    ]


def _structure_completeness(markdown: str, required_headers: List[str]) -> float:
    if not required_headers:
        return 1.0
    return round(sum(1 for header in required_headers if header in markdown) / float(len(required_headers)), 4)


def _numeric_consistency(claims: List[Dict[str, Any]]) -> float:
    total = 0
    matched = 0
    for claim in claims:
        text = str(claim.get("claim_text", ""))
        numeric_values = claim.get("numeric_values") if isinstance(claim, dict) else {}
        if not isinstance(numeric_values, dict):
            continue
        for value in numeric_values.values():
            try:
                num = float(value)
            except (TypeError, ValueError):
                continue
            total += 1
            if any(candidate in text for candidate in {f"{num:.0f}", f"{num:.1f}", f"{num:.2f}", str(value)}):
                matched += 1
    return round(float(matched) / float(total), 4) if total else 1.0


def _mean(values: Iterable[Any]) -> float:
    parsed = [float(value) for value in values]
    return round(sum(parsed) / float(len(parsed)), 4) if parsed else 0.0


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_dict(path: Path) -> Dict[str, Any]:
    return dict(_read_json(path)) if path.exists() else {}


def _read_list(path: Path) -> List[Dict[str, Any]]:
    payload = _read_json(path) if path.exists() else []
    return [dict(item) for item in payload] if isinstance(payload, list) else []


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _write_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""), encoding="utf-8")


def _render_summary_md(summary: Dict[str, Any]) -> str:
    taxonomy = summary.get("failure_taxonomy_summary", {})
    retrieval = summary.get("retrieval_ablation", {})
    lines = [
        "# Multi-Agent Regression Summary",
        "",
        "## Core Metrics",
        "",
        f"- sample_count: {summary['sample_count']}",
        f"- report_count: {summary['report_count']}",
        f"- evidence_coverage: {summary['evidence_coverage']}",
        f"- claim_grounded_rate: {summary['claim_grounded_rate']}",
        f"- verification_pass_rate: {summary.get('verification_pass_rate', 0.0)}",
        f"- unsupported_fallback_rate: {summary.get('unsupported_fallback_rate', 0.0)}",
        f"- skill_routed_task_rate: {summary.get('skill_routed_task_rate', 0.0)}",
        f"- citation_support_rate: {summary.get('citation_support_rate', 0.0)}",
        f"- numeric_accuracy: {summary['numeric_accuracy']}",
        f"- numeric_audit_pass_rate: {summary.get('numeric_audit_pass_rate', 0.0)}",
        f"- chart_consistency_pass_rate: {summary['chart_consistency_pass_rate']}",
        f"- contest_checklist_score_mean: {summary.get('contest_checklist_score_mean', 0.0)}",
        f"- contest_checklist_pass_rate_mean: {summary.get('contest_checklist_pass_rate_mean', 0.0)}",
        f"- revision_rate: {summary['revision_rate']}",
        f"- avg_duration_sec: {summary['avg_duration_sec']}",
        "",
        "## Failure Taxonomy",
        "",
    ]
    if isinstance(taxonomy, dict) and taxonomy:
        lines.extend(f"- {key}: {value}" for key, value in taxonomy.items())
    else:
        lines.append("- none: 0")
    lines.extend(["", "## Retrieval Ablation", ""])
    modes = retrieval.get("modes", {}) if isinstance(retrieval, dict) else {}
    if isinstance(modes, dict) and modes:
        for mode, metrics in modes.items():
            lines.append(
                f"- {mode}: alignment={metrics.get('evidence_alignment_mean')}, "
                f"coverage={metrics.get('evidence_coverage_mean')}, "
                f"verifier_pass={metrics.get('verifier_pass_rate')}"
            )
    else:
        lines.append("- no retrieval variants")
    lines.extend(["", "## Regression Topics", ""])
    for item in summary.get("regression_topics", []):
        if isinstance(item, dict):
            lines.append(f"- {item.get('id')}: {item.get('description')}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run multi-agent eval_v1 harness.")
    parser.add_argument("--config", default="configs/evaluation_stage12a.yaml")
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--eval-case-path", default=None)
    parser.add_argument("--max-samples", type=int, default=None)
    args = parser.parse_args()
    summary = run_multi_agent_evaluation(
        config_path=args.config,
        output_root=args.output_root,
        eval_case_path=args.eval_case_path,
        max_samples=args.max_samples,
    )
    print(f"[multi_agent_eval] summary: {summary['outputs']['evaluation_summary_json']}")
    print(f"[multi_agent_eval] per-report: {summary['outputs']['per_report_metrics_jsonl']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
