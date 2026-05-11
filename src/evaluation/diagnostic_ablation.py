"""Diagnostic-only ablation switches for Stage12 (no baseline override)."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from src.evaluation.numeric_audit import run_numeric_audit_for_case


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


def _extract_source_tag(text: str) -> str:
    lower = str(text).lower()
    for tag in ("financials", "filings", "news", "company_profile", "market"):
        if tag in lower:
            return tag
    return ""


def _topk_hit(source_types: List[str], gold_evidence_ids: List[str], k: int) -> bool:
    if not source_types or not gold_evidence_ids:
        return False
    gold_tags = {_extract_source_tag(x) for x in gold_evidence_ids}
    gold_tags.discard("")
    if not gold_tags:
        return False
    for source in source_types[:k]:
        if _extract_source_tag(source) in gold_tags:
            return True
    return False


def _mean(values: Iterable[float]) -> float:
    vals = list(values)
    if not vals:
        return 0.0
    return round(sum(vals) / float(len(vals)), 4)


def _recompute_numeric_accuracy(
    rows: List[Dict[str, object]],
    case_lookup: Dict[str, Dict[str, object]],
    abs_tol: float,
    rel_tol: float,
) -> Tuple[float, Dict[str, int]]:
    total_claims = 0
    total_supported = 0
    error_counter: Dict[str, int] = {}
    for row in rows:
        case_id = str(row.get("case_id", ""))
        case = case_lookup.get(case_id)
        if not case:
            continue
        claim_table_path = Path(str(dict(row.get("artifacts", {})).get("claim_table", "")))
        if not claim_table_path.exists():
            continue
        claims = list(_read_json(claim_table_path))
        result = run_numeric_audit_for_case(case=case, report_claims=claims, abs_tol=abs_tol, rel_tol=rel_tol)
        total_claims += int(result.get("numeric_claims", 0))
        total_supported += int(result.get("supported_numeric_claims", 0))
        for key, val in dict(result.get("error_breakdown", {})).items():
            error_counter[str(key)] = error_counter.get(str(key), 0) + int(val)
    accuracy = round(float(total_supported) / float(total_claims), 4) if total_claims else 0.0
    return accuracy, error_counter


def _iter_thresholds() -> List[float]:
    return [round(x / 100.0, 2) for x in range(50, 100, 5)]


def _compute_grounded_at_threshold(row: Dict[str, object], threshold: float) -> float:
    claim_table_path = Path(str(dict(row.get("artifacts", {})).get("claim_table", "")))
    if not claim_table_path.exists():
        return 0.0
    claims = list(_read_json(claim_table_path))
    if not claims:
        return 0.0
    passed = sum(1 for c in claims if _safe_float(c.get("confidence", 0.0)) >= threshold)
    return round(float(passed) / float(len(claims)), 4)


def _build_threshold_scan(rows: List[Dict[str, object]], run_root: Path) -> Dict[str, object]:
    out_dir = run_root / "verifier_threshold_scan"
    out_dir.mkdir(parents=True, exist_ok=True)

    threshold_rows: List[Dict[str, object]] = []
    task_types = sorted({str(r.get("task_type", "unknown")) for r in rows})
    for threshold in _iter_thresholds():
        per_case = [_compute_grounded_at_threshold(r, threshold) for r in rows]
        by_task: Dict[str, float] = {}
        for task in task_types:
            subset = [r for r in rows if str(r.get("task_type", "unknown")) == task]
            values = [_compute_grounded_at_threshold(r, threshold) for r in subset]
            by_task[task] = _mean(values)
        threshold_rows.append(
            {
                "threshold": threshold,
                "claim_grounded_rate": _mean(per_case),
                "by_task_type": by_task,
            }
        )

    best = max(threshold_rows, key=lambda x: float(x["claim_grounded_rate"])) if threshold_rows else {}

    csv_path = out_dir / "threshold_scan.csv"
    with csv_path.open("w", encoding="utf-8") as fh:
        headers = ["threshold", "claim_grounded_rate"] + [f"task_{t}" for t in task_types]
        fh.write(",".join(headers) + "\n")
        for row in threshold_rows:
            cols = [str(row["threshold"]), str(row["claim_grounded_rate"])]
            by_task = dict(row["by_task_type"])
            cols.extend(str(by_task.get(t, 0.0)) for t in task_types)
            fh.write(",".join(cols) + "\n")

    summary = {
        "threshold_rows": threshold_rows,
        "best_threshold_by_grounded_rate": best,
        "outputs": {
            "threshold_scan_csv": str(csv_path),
            "threshold_scan_md": str(out_dir / "threshold_scan.md"),
            "threshold_scan_json": str(out_dir / "threshold_scan.json"),
        },
    }
    (out_dir / "threshold_scan.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "# 验证阈值扫描诊断（Verifier Threshold Scan）",
        "",
        "说明：本诊断仅离线分析，不修改默认验证阈值（verifier_checkpoint.threshold）。",
        "",
        "| 阈值（verifier_checkpoint.threshold） | Claim 支撑率（claim_grounded_rate） |",
        "|---:|---:|",
    ]
    for row in threshold_rows:
        lines.append(f"| {row['threshold']} | {row['claim_grounded_rate']} |")
    lines.append("")
    if best:
        lines.append(
            f"- 最优阈值（best_threshold_by_grounded_rate）: {best['threshold']}，对应 Claim 支撑率（claim_grounded_rate）={best['claim_grounded_rate']}"
        )
    lines.append("")
    lines.append("## 按任务类型并排（task_type）")
    lines.append("")
    lines.append("| 阈值 | " + " | ".join(task_types) + " |")
    lines.append("|---:|" + "|".join(["---:"] * len(task_types)) + "|")
    for row in threshold_rows:
        by_task = dict(row["by_task_type"])
        lines.append("| " + str(row["threshold"]) + " | " + " | ".join(str(by_task.get(t, 0.0)) for t in task_types) + " |")
    (out_dir / "threshold_scan.md").write_text("\n".join(lines), encoding="utf-8")
    return summary


def run_diagnostic_ablation(
    eval_output_root: str | Path = "data/evaluation/eval_v1",
    baseline_report_root: str | Path = "reports/eval_v1",
    eval_case_path: str | Path = "data/eval_v1/cases.jsonl",
    output_root: str | Path = "reports/eval_v1_diagnostics",
    primary_variant: str = "bm25_real_writer",
    run_id: str | None = None,
) -> Dict[str, object]:
    """Run diagnostic switch comparisons into an isolated directory."""

    eval_root = Path(eval_output_root)
    baseline_root = Path(baseline_report_root)
    out_root = Path(output_root)
    run_name = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    run_root = out_root / run_name
    scenario_root = run_root / "scenarios"
    scenario_root.mkdir(parents=True, exist_ok=True)

    cases = {str(c.get("case_id", "")): c for c in _read_jsonl(Path(eval_case_path))}
    rows = [r for r in _read_jsonl(eval_root / "per_report_metrics.jsonl") if str(r.get("variant_id", "")) == primary_variant]

    scenarios = [
        {
            "id": "baseline_diag",
            "verifier_switch": "on",
            "writer_hit_switch": "top3",
            "numeric_matcher": "strict",
            "numeric_abs_tol": 0.2,
            "numeric_rel_tol": 0.02,
        },
        {
            "id": "verifier_off_diag",
            "verifier_switch": "off",
            "writer_hit_switch": "top3",
            "numeric_matcher": "strict",
            "numeric_abs_tol": 0.2,
            "numeric_rel_tol": 0.02,
        },
        {
            "id": "writer_top1_diag",
            "verifier_switch": "on",
            "writer_hit_switch": "top1",
            "numeric_matcher": "strict",
            "numeric_abs_tol": 0.2,
            "numeric_rel_tol": 0.02,
        },
        {
            "id": "numeric_relaxed_diag",
            "verifier_switch": "on",
            "writer_hit_switch": "top3",
            "numeric_matcher": "relaxed",
            "numeric_abs_tol": 150.0,
            "numeric_rel_tol": 1.0,
        },
    ]

    scenario_summaries: Dict[str, Dict[str, object]] = {}
    task_types = sorted({str(r.get("task_type", "unknown")) for r in rows})
    for scenario in scenarios:
        sid = str(scenario["id"])
        target_dir = scenario_root / sid
        target_dir.mkdir(parents=True, exist_ok=True)
        grounded_values = []
        writer_hits = []
        for row in rows:
            if str(scenario["verifier_switch"]) == "on":
                grounded_values.append(_safe_float(row.get("current_verifier_pass_ratio", 0.0)))
            else:
                grounded_values.append(_safe_float(row.get("evidence_coverage", 0.0)))
            hit_k = 1 if str(scenario["writer_hit_switch"]) == "top1" else 3
            case = cases.get(str(row.get("case_id", "")), {})
            source_types = [str(x) for x in list(row.get("reranked_topk_source_types", []))]
            gold_ids = [str(x) for x in list(case.get("gold_evidence_ids", []))]
            writer_hits.append(1.0 if _topk_hit(source_types, gold_ids, k=hit_k) else 0.0)

        numeric_accuracy, numeric_errors = _recompute_numeric_accuracy(
            rows=rows,
            case_lookup=cases,
            abs_tol=float(scenario["numeric_abs_tol"]),
            rel_tol=float(scenario["numeric_rel_tol"]),
        )
        summary = {
            "scenario_id": sid,
            "sample_count": len(rows),
            "verifier_switch": scenario["verifier_switch"],
            "writer_hit_switch": scenario["writer_hit_switch"],
            "numeric_matcher": scenario["numeric_matcher"],
            "claim_grounded_rate": _mean(grounded_values),
            "writer_hit_proxy": _mean(writer_hits),
            "numeric_accuracy": numeric_accuracy,
            "numeric_error_breakdown": numeric_errors,
        }
        by_task_type: Dict[str, Dict[str, float]] = {}
        for task in task_types:
            task_rows = [r for r in rows if str(r.get("task_type", "unknown")) == task]
            task_grounded = []
            task_writer_hit = []
            for row in task_rows:
                if str(scenario["verifier_switch"]) == "on":
                    task_grounded.append(_safe_float(row.get("current_verifier_pass_ratio", 0.0)))
                else:
                    task_grounded.append(_safe_float(row.get("evidence_coverage", 0.0)))
                hit_k = 1 if str(scenario["writer_hit_switch"]) == "top1" else 3
                case = cases.get(str(row.get("case_id", "")), {})
                source_types = [str(x) for x in list(row.get("reranked_topk_source_types", []))]
                gold_ids = [str(x) for x in list(case.get("gold_evidence_ids", []))]
                task_writer_hit.append(1.0 if _topk_hit(source_types, gold_ids, k=hit_k) else 0.0)
            task_numeric_accuracy, _ = _recompute_numeric_accuracy(
                rows=task_rows,
                case_lookup=cases,
                abs_tol=float(scenario["numeric_abs_tol"]),
                rel_tol=float(scenario["numeric_rel_tol"]),
            )
            by_task_type[task] = {
                "claim_grounded_rate": _mean(task_grounded),
                "writer_hit_proxy": _mean(task_writer_hit),
                "numeric_accuracy": task_numeric_accuracy,
            }
        summary["by_task_type"] = by_task_type
        (target_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        scenario_summaries[sid] = summary

    threshold_scan = _build_threshold_scan(rows=rows, run_root=run_root)
    baseline_summary = _read_json(baseline_root / "summary.json") if (baseline_root / "summary.json").exists() else {}
    comparison = {
        "run_id": run_name,
        "baseline_reference": baseline_summary,
        "scenario_summaries": scenario_summaries,
        "verifier_threshold_scan": threshold_scan,
        "outputs": {
            "comparison_json": str(run_root / "comparison_summary.json"),
            "comparison_md": str(run_root / "comparison_summary.md"),
        },
    }
    (run_root / "comparison_summary.json").write_text(json.dumps(comparison, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "# 诊断型消融并排对比（Diagnostic Ablation Comparison）",
        "",
        f"- 运行编号（run_id）: {run_name}",
        f"- 主分析变体（primary_variant）: {primary_variant}",
        f"- 基线摘要（baseline_summary）: {baseline_root / 'summary.json'}",
        "",
        "## 全局并排",
        "",
        "| 场景（scenario） | verifier 开关 | writer 命中代理开关 | numeric 匹配器 | Claim 支撑率（claim_grounded_rate） | Writer 命中代理（writer_hit_proxy） | 数字准确率（numeric_accuracy） |",
        "|---|---|---|---|---:|---:|---:|",
    ]
    for sid in ["baseline_diag", "verifier_off_diag", "writer_top1_diag", "numeric_relaxed_diag"]:
        s = scenario_summaries[sid]
        lines.append(
            f"| {sid} | {s['verifier_switch']} | {s['writer_hit_switch']} | {s['numeric_matcher']} | {s['claim_grounded_rate']} | {s['writer_hit_proxy']} | {s['numeric_accuracy']} |"
        )
    lines.append("")
    lines.append("## 按任务类型并排（task_type）")
    lines.append("")
    for task in task_types:
        lines.append(f"### 任务类型（task_type）: {task}")
        lines.append("")
        lines.append("| 场景 | Claim 支撑率（claim_grounded_rate） | Writer 命中代理（writer_hit_proxy） | 数字准确率（numeric_accuracy） |")
        lines.append("|---|---:|---:|---:|")
        for sid in ["baseline_diag", "verifier_off_diag", "writer_top1_diag", "numeric_relaxed_diag"]:
            s = scenario_summaries[sid]
            t = dict(s.get("by_task_type", {})).get(task, {})
            lines.append(
                f"| {sid} | {t.get('claim_grounded_rate', 0.0)} | {t.get('writer_hit_proxy', 0.0)} | {t.get('numeric_accuracy', 0.0)} |"
            )
        lines.append("")
    lines.append("## 风险说明")
    lines.append("")
    lines.append("- 本诊断只读取既有产物进行离线计算，不改默认流程。")
    lines.append("- 未修改 retrieval 主逻辑、writer 核心生成策略、verifier 判定逻辑。")
    lines.append("- verifier 阈值扫描为离线分析结果，不会写回 checkpoint。")
    (run_root / "comparison_summary.md").write_text("\n".join(lines), encoding="utf-8")
    return comparison
