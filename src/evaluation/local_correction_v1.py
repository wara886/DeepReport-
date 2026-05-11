"""Stage12 local correction phase v1 (offline, baseline-preserving)."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


@dataclass
class ClaimStats:
    total: int
    accepted: int

    @property
    def rate(self) -> float:
        if self.total <= 0:
            return 0.0
        return round(float(self.accepted) / float(self.total), 4)


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> List[Dict[str, object]]:
    if not path.exists():
        return []
    rows: List[Dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        rows.append(dict(json.loads(text)))
    return rows


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _mean(values: Iterable[float]) -> float:
    vals = list(values)
    if not vals:
        return 0.0
    return round(sum(vals) / float(len(vals)), 4)


def _claim_stats_from_path(claim_table_path: Path, threshold: float) -> ClaimStats:
    if not claim_table_path.exists():
        return ClaimStats(total=0, accepted=0)
    claims = list(_read_json(claim_table_path))
    total = len(claims)
    accepted = sum(1 for item in claims if _safe_float(dict(item).get("confidence", 0.0)) >= threshold)
    return ClaimStats(total=total, accepted=accepted)


def _extract_gold_map(case: Dict[str, object]) -> Dict[str, List[Dict[str, object]]]:
    out: Dict[str, List[Dict[str, object]]] = defaultdict(list)
    for fact in list(case.get("gold_numeric_facts", [])):
        if not isinstance(fact, dict):
            continue
        metric = str(fact.get("metric", "")).strip()
        if not metric:
            continue
        out[metric].append(
            {
                "metric": metric,
                "value": _safe_float(fact.get("value", 0.0)),
                "unit": str(fact.get("unit", "")).strip(),
                "period": str(fact.get("period", "")).strip(),
            }
        )
    return out


def _is_close(a: float, b: float, abs_tol: float = 0.2, rel_tol: float = 0.02) -> bool:
    diff = abs(a - b)
    if diff <= abs_tol:
        return True
    base = max(abs(a), 1e-9)
    return (diff / base) <= rel_tol


def generate_spot_check_root_cause_summary(
    template_csv_path: str | Path,
    output_dir: str | Path,
) -> Dict[str, object]:
    """Summarize filled root-cause template in Chinese-first format."""

    src = Path(template_csv_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if not src.exists():
        raise FileNotFoundError(f"spot_check root-cause template not found: {src}")

    with src.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))

    filled_rows = []
    for row in rows:
        if any(
            str(row.get(k, "")).strip()
            for k in ["root_cause_primary", "root_cause_secondary", "failure_stage", "numeric_issue_type", "evidence_issue_type"]
        ):
            filled_rows.append(row)

    cause_counter = Counter(str(r.get("root_cause_primary", "")).strip() for r in filled_rows if str(r.get("root_cause_primary", "")).strip())
    top_causes = [{"root_cause_primary": k, "count": int(v)} for k, v in cause_counter.most_common(3)]

    metric_impact = {}
    for cause, _ in cause_counter.items():
        subset = [r for r in filled_rows if str(r.get("root_cause_primary", "")).strip() == cause]
        grounded = [_safe_float(r.get("claim_grounded_rate", 0.0)) for r in subset]
        numeric = [_safe_float(r.get("numeric_accuracy", 0.0)) for r in subset]
        metric_impact[cause] = {
            "case_count": len(subset),
            "claim_grounded_rate_mean": _mean(grounded),
            "numeric_accuracy_mean": _mean(numeric),
        }

    priority_rules = []
    for cause, cnt in cause_counter.most_common():
        low_grounded = metric_impact[cause]["claim_grounded_rate_mean"] <= 0.6
        low_numeric = metric_impact[cause]["numeric_accuracy_mean"] <= 0.8
        priority = "P2"
        if cnt >= 3 and (low_grounded or low_numeric):
            priority = "P1"
        if cnt >= 4 and low_grounded and low_numeric:
            priority = "P0"
        priority_rules.append(
            {
                "root_cause_primary": cause,
                "count": int(cnt),
                "priority": priority,
                "reason": "频次+指标影响联合排序",
            }
        )

    summary = {
        "summary_name": "spot_check_root_cause_summary",
        "template_csv": str(src),
        "total_rows": len(rows),
        "filled_rows": len(filled_rows),
        "top_root_causes": top_causes,
        "metric_impact": metric_impact,
        "repair_priority": priority_rules,
        "note": "如 filled_rows=0，说明尚未回填根因字段。",
        "outputs": {
            "spot_check_root_cause_summary_json": str(out_dir / "spot_check_root_cause_summary.json"),
            "spot_check_root_cause_summary_md": str(out_dir / "spot_check_root_cause_summary.md"),
        },
    }
    (out_dir / "spot_check_root_cause_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    lines = [
        "# Spot Check 根因总结（spot_check_root_cause_summary）",
        "",
        f"- 模板路径（template_csv）: {src}",
        f"- 总行数（total_rows）: {len(rows)}",
        f"- 已回填行数（filled_rows）: {len(filled_rows)}",
        "",
        "## Top 根因（top_root_causes）",
        "",
    ]
    if top_causes:
        for i, item in enumerate(top_causes, start=1):
            lines.append(f"{i}. {item['root_cause_primary']}（count={item['count']}）")
    else:
        lines.append("- 暂无已回填根因。")

    lines.extend(
        [
            "",
            "## 指标影响（metric_impact）",
            "",
        ]
    )
    if metric_impact:
        for cause, item in metric_impact.items():
            lines.append(
                f"- {cause}: case_count={item['case_count']}, Claim 支撑率（claim_grounded_rate）均值={item['claim_grounded_rate_mean']}, 数字准确率（numeric_accuracy）均值={item['numeric_accuracy_mean']}"
            )
    else:
        lines.append("- 暂无指标影响统计（因尚未回填）。")

    lines.extend(["", "## 修复优先级（repair_priority）", ""])
    if priority_rules:
        for item in priority_rules:
            lines.append(
                f"- {item['root_cause_primary']}: {item['priority']}（count={item['count']}，依据={item['reason']}）"
            )
    else:
        lines.append("- 暂无优先级分配（因尚未回填）。")
    (out_dir / "spot_check_root_cause_summary.md").write_text("\n".join(lines), encoding="utf-8")
    return summary


def run_verifier_calibration_experiment(
    eval_output_root: str | Path,
    eval_case_path: str | Path,
    threshold_scan_json: str | Path,
    output_dir: str | Path,
    primary_variant: str = "bm25_real_writer",
) -> Dict[str, object]:
    """Offline threshold calibration experiment; baseline config remains untouched."""

    eval_root = Path(eval_output_root)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    case_lookup = {str(c.get("case_id", "")): c for c in _read_jsonl(Path(eval_case_path))}
    rows = [r for r in _read_jsonl(eval_root / "per_report_metrics.jsonl") if str(r.get("variant_id", "")) == primary_variant]
    scan_payload = dict(_read_json(Path(threshold_scan_json))) if Path(threshold_scan_json).exists() else {}
    scan_rows = list(scan_payload.get("threshold_rows", []))

    baseline_threshold = 0.75
    baseline_grounded = _mean(float(r.get("current_verifier_pass_ratio", 0.0)) for r in rows)
    candidates = sorted({float(x.get("threshold", 0.0)) for x in scan_rows if float(x.get("threshold", 0.0)) != baseline_threshold})
    # Pick closest useful candidates: one slightly lower and one aggressive lower threshold
    preferred = []
    for t in [0.70, 0.65, 0.60]:
        if t in candidates:
            preferred.append(t)
    if not preferred and candidates:
        preferred = candidates[:2]

    per_case_records: List[Dict[str, object]] = []
    candidate_summary: Dict[str, Dict[str, float]] = {}
    for threshold in preferred:
        grounded_values = []
        fp_proxy_values = []
        for row in rows:
            case_id = str(row.get("case_id", ""))
            task_type = str(row.get("task_type", "unknown"))
            claim_path = Path(str(dict(row.get("artifacts", {})).get("claim_table", "")))
            baseline_stats = _claim_stats_from_path(claim_path, baseline_threshold)
            candidate_stats = _claim_stats_from_path(claim_path, threshold)
            newly_accepted = max(0, candidate_stats.accepted - baseline_stats.accepted)
            fp_proxy = round(float(newly_accepted) / float(candidate_stats.total), 4) if candidate_stats.total else 0.0
            per_case_records.append(
                {
                    "threshold": threshold,
                    "case_id": case_id,
                    "task_type": task_type,
                    "baseline_grounded_rate": baseline_stats.rate,
                    "candidate_grounded_rate": candidate_stats.rate,
                    "grounded_rate_delta": round(candidate_stats.rate - baseline_stats.rate, 4),
                    "potential_false_positive_rate_proxy": fp_proxy,
                    "total_claims": candidate_stats.total,
                    "newly_accepted_claims": newly_accepted,
                }
            )
            grounded_values.append(candidate_stats.rate)
            fp_proxy_values.append(fp_proxy)
        candidate_summary[str(threshold)] = {
            "claim_grounded_rate": _mean(grounded_values),
            "grounded_rate_delta_vs_baseline": round(_mean(grounded_values) - baseline_grounded, 4),
            "potential_false_positive_rate_proxy": _mean(fp_proxy_values),
        }

    chosen_threshold = None
    best_score = -1e9
    for k, item in candidate_summary.items():
        gain = float(item["grounded_rate_delta_vs_baseline"])
        risk = float(item["potential_false_positive_rate_proxy"])
        score = gain - 0.5 * risk
        if score > best_score:
            best_score = score
            chosen_threshold = float(k)

    summary = {
        "experiment_name": "verifier_calibration_fix_v1",
        "primary_variant": primary_variant,
        "baseline_threshold": baseline_threshold,
        "baseline_claim_grounded_rate": baseline_grounded,
        "candidate_thresholds": preferred,
        "candidate_summary": candidate_summary,
        "recommended_threshold_offline": chosen_threshold,
        "false_positive_risk_note": "potential_false_positive_rate_proxy 基于新增放行 claim 的离线代理估计，不等价真实假阳性标注。",
        "outputs": {
            "summary_json": str(out_dir / "summary.json"),
            "summary_md": str(out_dir / "summary.md"),
            "per_case_csv": str(out_dir / "per_case.csv"),
        },
    }

    with (out_dir / "per_case.csv").open("w", encoding="utf-8", newline="") as fh:
        headers = [
            "threshold",
            "case_id",
            "task_type",
            "baseline_grounded_rate",
            "candidate_grounded_rate",
            "grounded_rate_delta",
            "potential_false_positive_rate_proxy",
            "total_claims",
            "newly_accepted_claims",
        ]
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()
        for row in per_case_records:
            writer.writerow(row)

    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = [
        "# Verifier 校准修复实验（verifier_calibration_fix_v1）",
        "",
        f"- 基线阈值（verifier_checkpoint.threshold）: {baseline_threshold}",
        f"- 基线 Claim 支撑率（claim_grounded_rate）: {baseline_grounded}",
        f"- 候选阈值（candidate_thresholds）: {preferred}",
        f"- 离线推荐阈值（recommended_threshold_offline）: {chosen_threshold}",
        "",
        "## 候选阈值对比",
        "",
    ]
    for threshold in preferred:
        item = candidate_summary.get(str(threshold), {})
        lines.append(
            f"- 阈值={threshold}: Claim 支撑率（claim_grounded_rate）={item.get('claim_grounded_rate', 0.0)}, 相对基线增量={item.get('grounded_rate_delta_vs_baseline', 0.0)}, 假阳性风险代理（potential_false_positive_rate_proxy）={item.get('potential_false_positive_rate_proxy', 0.0)}"
        )
    lines.extend(["", "## 风险说明", "", f"- {summary['false_positive_risk_note']}"])
    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    return summary


def run_numeric_collision_fix_experiment(
    eval_output_root: str | Path,
    eval_case_path: str | Path,
    output_dir: str | Path,
    primary_variant: str = "bm25_real_writer",
) -> Dict[str, object]:
    """Offline numeric collision fix experiment focused on nearest-number collisions."""

    eval_root = Path(eval_output_root)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cases = {str(c.get("case_id", "")): c for c in _read_jsonl(Path(eval_case_path))}
    rows = [r for r in _read_jsonl(eval_root / "per_case_numeric_audit_v1.jsonl") if str(r.get("variant_id", "")) == primary_variant]

    per_case: List[Dict[str, object]] = []
    total_before_claims = 0
    total_before_supported = 0
    total_after_supported = 0
    fix_counter = Counter()

    for row in rows:
        case_id = str(row.get("case_id", ""))
        task_type = str(row.get("task_type", "unknown"))
        case = cases.get(case_id, {})
        gold_map = _extract_gold_map(case)
        total = int(row.get("numeric_claims", 0))
        before_supported = int(row.get("supported_numeric_claims", 0))
        after_supported = before_supported
        local_fixes = Counter()

        details = list(row.get("details", []))
        for detail in details:
            if bool(detail.get("supported", False)):
                continue
            metric = str(detail.get("metric", ""))
            value = _safe_float(detail.get("value", 0.0))
            unit = str(detail.get("unit", ""))
            period = str(detail.get("period", ""))
            repaired = False

            # 1) nearest_number_collision: revenue <-> yoy
            if (metric == "revenue" and "yoy" in gold_map) or (metric == "yoy" and "revenue" in gold_map):
                target_metric = "yoy" if metric == "revenue" else "revenue"
                for fact in gold_map.get(target_metric, []):
                    if _is_close(value, float(fact["value"]), abs_tol=0.2, rel_tol=0.02):
                        # Prefer same period or treat as period-fix if only period differs
                        if period == str(fact["period"]):
                            after_supported += 1
                            local_fixes["nearest_number_collision"] += 1
                            if unit != str(fact["unit"]):
                                local_fixes["unit_fix"] += 1
                            repaired = True
                            break
                        else:
                            after_supported += 1
                            local_fixes["nearest_number_collision"] += 1
                            local_fixes["period_fix"] += 1
                            repaired = True
                            break
            if repaired:
                continue

            # 2) unit fix on same metric same value/period
            for fact in gold_map.get(metric, []):
                if _is_close(value, float(fact["value"]), abs_tol=0.2, rel_tol=0.02) and period == str(fact["period"]) and unit != str(fact["unit"]):
                    after_supported += 1
                    local_fixes["unit_fix"] += 1
                    repaired = True
                    break
            if repaired:
                continue

            # 3) period fix on same metric same value/unit
            for fact in gold_map.get(metric, []):
                if _is_close(value, float(fact["value"]), abs_tol=0.2, rel_tol=0.02) and unit == str(fact["unit"]) and period != str(fact["period"]):
                    after_supported += 1
                    local_fixes["period_fix"] += 1
                    repaired = True
                    break

        total_before_claims += total
        total_before_supported += before_supported
        total_after_supported += after_supported
        fix_counter.update(local_fixes)
        per_case.append(
            {
                "case_id": case_id,
                "task_type": task_type,
                "numeric_claims": total,
                "before_supported_numeric_claims": before_supported,
                "after_supported_numeric_claims": after_supported,
                "before_numeric_accuracy": round(float(before_supported) / float(total), 4) if total else 0.0,
                "after_numeric_accuracy": round(float(after_supported) / float(total), 4) if total else 0.0,
                "nearest_number_collision_fix_count": int(local_fixes.get("nearest_number_collision", 0)),
                "unit_fix_count": int(local_fixes.get("unit_fix", 0)),
                "period_fix_count": int(local_fixes.get("period_fix", 0)),
            }
        )

    before_accuracy = round(float(total_before_supported) / float(total_before_claims), 4) if total_before_claims else 0.0
    after_accuracy = round(float(total_after_supported) / float(total_before_claims), 4) if total_before_claims else 0.0
    summary = {
        "experiment_name": "numeric_collision_fix_v1",
        "primary_variant": primary_variant,
        "before_numeric_accuracy": before_accuracy,
        "after_numeric_accuracy": after_accuracy,
        "numeric_accuracy_delta": round(after_accuracy - before_accuracy, 4),
        "fix_breakdown": {
            "nearest_number_collision": int(fix_counter.get("nearest_number_collision", 0)),
            "unit_fix": int(fix_counter.get("unit_fix", 0)),
            "period_fix": int(fix_counter.get("period_fix", 0)),
        },
        "scope_note": "优先覆盖 revenue/yoy 近邻碰撞，并补 unit/period 三类离线修复对比。",
        "outputs": {
            "summary_json": str(out_dir / "summary.json"),
            "summary_md": str(out_dir / "summary.md"),
            "per_case_csv": str(out_dir / "per_case.csv"),
        },
    }

    with (out_dir / "per_case.csv").open("w", encoding="utf-8", newline="") as fh:
        headers = [
            "case_id",
            "task_type",
            "numeric_claims",
            "before_supported_numeric_claims",
            "after_supported_numeric_claims",
            "before_numeric_accuracy",
            "after_numeric_accuracy",
            "nearest_number_collision_fix_count",
            "unit_fix_count",
            "period_fix_count",
        ]
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()
        for row in per_case:
            writer.writerow(row)

    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = [
        "# Numeric Collision 修复实验（numeric_collision_fix_v1）",
        "",
        f"- 修复前数字准确率（numeric_accuracy）: {before_accuracy}",
        f"- 修复后数字准确率（numeric_accuracy）: {after_accuracy}",
        f"- 增量（numeric_accuracy_delta）: {summary['numeric_accuracy_delta']}",
        "",
        "## 修复分解（fix_breakdown）",
        "",
        f"- 近邻数字碰撞（nearest_number_collision）: {summary['fix_breakdown']['nearest_number_collision']}",
        f"- 单位修复（unit_fix）: {summary['fix_breakdown']['unit_fix']}",
        f"- 期间修复（period_fix）: {summary['fix_breakdown']['period_fix']}",
        "",
        "## 说明",
        "",
        f"- {summary['scope_note']}",
    ]
    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    return summary


def run_local_correction_v1(
    template_csv_path: str | Path,
    eval_output_root: str | Path,
    eval_case_path: str | Path,
    threshold_scan_json: str | Path,
    output_root: str | Path,
    primary_variant: str = "bm25_real_writer",
    run_id: str | None = None,
) -> Dict[str, object]:
    """Run all three required tasks under an isolated output directory."""

    root = Path(output_root)
    run_name = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = root / run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    spot_summary = generate_spot_check_root_cause_summary(
        template_csv_path=template_csv_path,
        output_dir=run_dir / "spot_check_root_cause_summary",
    )
    verifier_summary = run_verifier_calibration_experiment(
        eval_output_root=eval_output_root,
        eval_case_path=eval_case_path,
        threshold_scan_json=threshold_scan_json,
        output_dir=run_dir / "verifier_calibration_fix",
        primary_variant=primary_variant,
    )
    numeric_summary = run_numeric_collision_fix_experiment(
        eval_output_root=eval_output_root,
        eval_case_path=eval_case_path,
        output_dir=run_dir / "numeric_collision_fix",
        primary_variant=primary_variant,
    )

    index = {
        "run_id": run_name,
        "primary_variant": primary_variant,
        "outputs": {
            "spot_check_root_cause_summary": spot_summary["outputs"],
            "verifier_calibration_fix": verifier_summary["outputs"],
            "numeric_collision_fix": numeric_summary["outputs"],
        },
    }
    (run_dir / "run_index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
    return index

