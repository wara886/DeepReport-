"""Grounding rule experiment v2 batch runner (standalone)."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from src.grounding_rule_experiment import ExperimentPaths, run_grounding_rule_experiment


def _read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _write_csv(path: Path, rows: List[Dict[str, object]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _bool_str(v: object) -> bool:
    return str(v).strip().lower() in {"true", "1", "yes"}


@dataclass
class CaseDiscovery:
    case_id: str
    case_dir: Path
    claim_table: Path
    manifest_json: Path
    verification_report: Path | None
    review_csv: Path | None
    variant: str
    symbol: str
    period: str


def discover_eval_v1_cases(project_root: Path, eval_runs_dir: str = "data/evaluation/eval_v1/runs") -> List[CaseDiscovery]:
    root = (project_root / eval_runs_dir).resolve()
    if not root.exists():
        raise FileNotFoundError(f"eval_v1 runs 目录不存在: {root}")

    cases: List[CaseDiscovery] = []
    for claim_table in sorted(root.glob("*/*/*/outputs/claim_table.json")):
        variant_dir = claim_table.parents[1]
        symbol = variant_dir.parents[1].name
        period = variant_dir.parents[0].name
        variant = variant_dir.name
        case_id = f"{symbol}:{period}:{variant}"
        reports_dir = variant_dir / "reports"
        review_csv = None
        for candidate_name in ["claim_review_backfill_v2.csv", "claim_review_backfill.csv"]:
            candidate = reports_dir / candidate_name
            if candidate.exists():
                review_csv = candidate
                break
        manifest_json = variant_dir / "curated" / "real_data_manifest.json"
        verification_report = variant_dir / "outputs" / "verification_report.json"
        cases.append(
            CaseDiscovery(
                case_id=case_id,
                case_dir=variant_dir,
                claim_table=claim_table,
                manifest_json=manifest_json,
                verification_report=verification_report if verification_report.exists() else None,
                review_csv=review_csv,
                variant=variant,
                symbol=symbol,
                period=period,
            )
        )
    return cases


def run_grounding_rule_experiment_v2_batch(
    project_root: Path,
    eval_runs_dir: str = "data/evaluation/eval_v1/runs",
    output_dir: str = "artifacts/grounding_rule_experiment_v2_batch",
) -> Dict[str, object]:
    out_dir = (project_root / output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    case_artifacts_dir = out_dir / "cases"
    case_artifacts_dir.mkdir(parents=True, exist_ok=True)

    discovered = discover_eval_v1_cases(project_root=project_root, eval_runs_dir=eval_runs_dir)
    if not discovered:
        raise ValueError("未发现可用 case（claim_table.json）。")

    per_case_rows: List[Dict[str, object]] = []
    per_claim_all_rows: List[Dict[str, object]] = []

    direct_baseline_sum = 0
    direct_rule_aware_sum = 0
    direct_count_sum = 0
    derived_changed_sum = 0
    derived_count_sum = 0
    potential_fp_claim_ids: List[str] = []
    false_negative_to_pass_all: List[str] = []
    insufficient_cases: List[str] = []
    sufficient_cases: List[str] = []

    for case in discovered:
        if not case.manifest_json.exists():
            insufficient_cases.append(case.case_id)
            per_case_rows.append(
                {
                    "case_id": case.case_id,
                    "symbol": case.symbol,
                    "period": case.period,
                    "variant": case.variant,
                    "status": "insufficient_review_data",
                    "insufficient_reason": "missing_manifest_json",
                    "claim_count": "",
                    "direct_claim_count": "",
                    "derived_claim_count": "",
                    "direct_grounded_rate_baseline": "",
                    "direct_grounded_rate_rule_aware": "",
                    "direct_grounded_rate_delta": "",
                    "derived_changed_count": "",
                    "potential_false_positive_claim_ids": "",
                    "false_negative_to_pass_claim_ids": "",
                }
            )
            continue

        if case.review_csv is None:
            insufficient_cases.append(case.case_id)
            claim_rows = list(json.loads(case.claim_table.read_text(encoding="utf-8")))
            for claim in claim_rows:
                per_claim_all_rows.append(
                    {
                        "case_id": case.case_id,
                        "symbol": case.symbol,
                        "period": case.period,
                        "variant": case.variant,
                        "experiment_status": "insufficient_review_data",
                        "claim_id": str(claim.get("claim_id", "")),
                        "section_name": str(claim.get("section_name", "")),
                        "claim_type": "",
                        "confidence": str(claim.get("confidence", "")),
                        "baseline_is_grounded": "",
                        "rule_aware_is_grounded": "",
                        "status_transition": "insufficient_review_data",
                        "rule_branch": "",
                        "review_root_cause_primary": "",
                    }
                )
            per_case_rows.append(
                {
                    "case_id": case.case_id,
                    "symbol": case.symbol,
                    "period": case.period,
                    "variant": case.variant,
                    "status": "insufficient_review_data",
                    "insufficient_reason": "missing_review_csv",
                    "claim_count": len(claim_rows),
                    "direct_claim_count": "",
                    "derived_claim_count": "",
                    "direct_grounded_rate_baseline": "",
                    "direct_grounded_rate_rule_aware": "",
                    "direct_grounded_rate_delta": "",
                    "derived_changed_count": "",
                    "potential_false_positive_claim_ids": "",
                    "false_negative_to_pass_claim_ids": "",
                }
            )
            continue

        sufficient_cases.append(case.case_id)
        case_output = case_artifacts_dir / case.case_id.replace(":", "__")
        paths = ExperimentPaths(
            claim_table=case.claim_table,
            review_csv=case.review_csv,
            manifest_json=case.manifest_json,
            output_dir=case_output,
            verification_report=case.verification_report,
        )
        summary = run_grounding_rule_experiment(paths)
        per_claim_csv = Path(summary["outputs"]["per_claim_csv"])
        claim_rows = _read_csv(per_claim_csv)

        for row in claim_rows:
            per_claim_all_rows.append(
                {
                    "case_id": case.case_id,
                    "symbol": case.symbol,
                    "period": case.period,
                    "variant": case.variant,
                    "experiment_status": "ok",
                    **row,
                }
            )

        direct_rows = [r for r in claim_rows if r.get("claim_type") == "direct_factual_extraction"]
        derived_rows = [r for r in claim_rows if r.get("claim_type") == "derived_aggregated"]
        direct_baseline = sum(1 for r in direct_rows if _bool_str(r.get("baseline_is_grounded")))
        direct_rule = sum(1 for r in direct_rows if _bool_str(r.get("rule_aware_is_grounded")))
        derived_changed = sum(1 for r in derived_rows if _bool_str(r.get("changed")))

        direct_baseline_sum += direct_baseline
        direct_rule_aware_sum += direct_rule
        direct_count_sum += len(direct_rows)
        derived_changed_sum += derived_changed
        derived_count_sum += len(derived_rows)

        suspicious = list(summary.get("false_positive_risk", {}).get("suspicious_new_accept_claim_ids", []))
        false_negative_to_pass = list(summary.get("false_negative_to_pass_claim_ids", []))
        potential_fp_claim_ids.extend([f"{case.case_id}:{cid}" for cid in suspicious])
        false_negative_to_pass_all.extend([f"{case.case_id}:{cid}" for cid in false_negative_to_pass])

        rate_baseline = (direct_baseline / float(len(direct_rows))) if direct_rows else 0.0
        rate_rule = (direct_rule / float(len(direct_rows))) if direct_rows else 0.0
        per_case_rows.append(
            {
                "case_id": case.case_id,
                "symbol": case.symbol,
                "period": case.period,
                "variant": case.variant,
                "status": "ok",
                "insufficient_reason": "",
                "claim_count": len(claim_rows),
                "direct_claim_count": len(direct_rows),
                "derived_claim_count": len(derived_rows),
                "direct_grounded_rate_baseline": round(rate_baseline, 4),
                "direct_grounded_rate_rule_aware": round(rate_rule, 4),
                "direct_grounded_rate_delta": round(rate_rule - rate_baseline, 4),
                "derived_changed_count": derived_changed,
                "potential_false_positive_claim_ids": "|".join(suspicious),
                "false_negative_to_pass_claim_ids": "|".join(false_negative_to_pass),
            }
        )

    total_cases = len(discovered)
    sufficient_count = len(sufficient_cases)
    insufficient_count = len(insufficient_cases)
    covered_ratio = (sufficient_count / float(total_cases)) if total_cases else 0.0
    direct_rate_baseline = (direct_baseline_sum / float(direct_count_sum)) if direct_count_sum else 0.0
    direct_rate_rule = (direct_rule_aware_sum / float(direct_count_sum)) if direct_count_sum else 0.0
    direct_rate_delta = direct_rate_rule - direct_rate_baseline
    derived_stability_rate = (1.0 - (derived_changed_sum / float(derived_count_sum))) if derived_count_sum else 1.0

    precondition_ready = (
        sufficient_count >= 5 and covered_ratio >= 0.6 and (not potential_fp_claim_ids) and derived_stability_rate >= 0.98
    )
    precondition_reason = (
        "满足灰度前置条件。"
        if precondition_ready
        else "未满足灰度前置条件：请先补齐 review 数据并扩展多样本验证后再评估灰度。"
    )

    batch_summary = {
        "experiment_name": "grounding_rule_experiment_v2_batch",
        "rules": {
            "baseline": "is_grounded = confidence >= 0.75",
            "rule_aware": "direct_factual_extraction: baseline OR direct_supported; derived_aggregated: baseline only",
        },
        "case_coverage": {
            "discovered_case_count": total_cases,
            "sufficient_case_count": sufficient_count,
            "insufficient_case_count": insufficient_count,
            "covered_ratio": round(covered_ratio, 4),
            "insufficient_case_ids": insufficient_cases,
        },
        "direct_factual_grounded_rate": {
            "baseline": round(direct_rate_baseline, 4),
            "rule_aware": round(direct_rate_rule, 4),
            "delta": round(direct_rate_delta, 4),
        },
        "derived_stability": {
            "derived_claim_count": derived_count_sum,
            "derived_changed_count": derived_changed_sum,
            "stability_rate": round(derived_stability_rate, 4),
        },
        "potential_false_positive": {
            "count": len(potential_fp_claim_ids),
            "claim_ids": potential_fp_claim_ids,
            "flag": bool(potential_fp_claim_ids),
        },
        "false_negative_to_pass_claim_ids": false_negative_to_pass_all,
        "precondition_for_canary": {
            "ready": precondition_ready,
            "reason": precondition_reason,
        },
        "outputs": {
            "batch_summary_json": str(out_dir / "batch_summary.json"),
            "batch_summary_md": str(out_dir / "batch_summary.md"),
            "per_case_summary_csv": str(out_dir / "per_case_summary.csv"),
            "per_claim_all_csv": str(out_dir / "per_claim_all.csv"),
        },
    }

    _write_csv(
        out_dir / "per_case_summary.csv",
        rows=per_case_rows,
        fieldnames=[
            "case_id",
            "symbol",
            "period",
            "variant",
            "status",
            "insufficient_reason",
            "claim_count",
            "direct_claim_count",
            "derived_claim_count",
            "direct_grounded_rate_baseline",
            "direct_grounded_rate_rule_aware",
            "direct_grounded_rate_delta",
            "derived_changed_count",
            "potential_false_positive_claim_ids",
            "false_negative_to_pass_claim_ids",
        ],
    )

    _write_csv(
        out_dir / "per_claim_all.csv",
        rows=per_claim_all_rows,
        fieldnames=[
            "case_id",
            "symbol",
            "period",
            "variant",
            "experiment_status",
            "claim_id",
            "section_name",
            "claim_type",
            "confidence",
            "baseline_is_grounded",
            "rule_aware_is_grounded",
            "status_transition",
            "rule_branch",
            "review_root_cause_primary",
        ],
    )

    (out_dir / "batch_summary.json").write_text(json.dumps(batch_summary, indent=2, ensure_ascii=False), encoding="utf-8")

    md_lines = [
        "# Grounding 规则实验 v2 批量总结",
        "",
        "## 样本覆盖",
        "",
        f"- 发现 case 数: {total_cases}",
        f"- 可评估 case 数: {sufficient_count}",
        f"- review 输入不足 case 数: {insufficient_count}",
        f"- 覆盖率: {round(covered_ratio, 4)}",
        "",
        "## direct factual grounded rate 提升",
        "",
        f"- baseline: {round(direct_rate_baseline, 4)}",
        f"- rule-aware: {round(direct_rate_rule, 4)}",
        f"- 提升 delta: {round(direct_rate_delta, 4)}",
        "",
        "## derived 稳定性",
        "",
        f"- derived claim 总数: {derived_count_sum}",
        f"- derived 变化数: {derived_changed_sum}",
        f"- 稳定率: {round(derived_stability_rate, 4)}",
        "",
        "## 潜在假阳性",
        "",
        f"- 潜在假阳性条目数: {len(potential_fp_claim_ids)}",
        f"- 条目列表: {potential_fp_claim_ids}",
        "",
        "## 误杀转通过条目",
        "",
        f"- false_negative_to_pass: {false_negative_to_pass_all}",
        "",
        "## 灰度前置条件",
        "",
        f"- ready: {precondition_ready}",
        f"- reason: {precondition_reason}",
        "",
        "## 数据完整性提示",
        "",
        "- 对缺失 review 输入的 case，本批次统一标记为 insufficient_review_data，并且不输出伪造结论。",
        f"- insufficient case 列表: {insufficient_cases}",
        "",
        "## 风险与局限",
        "",
        "- 本批次仍是离线规则实验，不等于线上策略切换。",
        "- 若 review 覆盖不足，汇总结果可能低估或高估真实效果。",
        "- 当前结果依赖现有 review 质量与字段一致性，需持续抽检。",
        "",
    ]
    (out_dir / "batch_summary.md").write_text("\n".join(md_lines), encoding="utf-8")

    return batch_summary
