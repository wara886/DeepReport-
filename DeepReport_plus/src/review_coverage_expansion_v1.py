"""Review coverage expansion v1 (standalone analytics and queue builder)."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_csv(path: Path, rows: List[Dict[str, object]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _pick_review_csv(reports_dir: Path) -> tuple[Path | None, str]:
    preferred = [
        ("claim_review_backfill_v2.csv", "v2"),
        ("claim_review_backfill.csv", "v1"),
    ]
    for file_name, ver in preferred:
        candidate = reports_dir / file_name
        if candidate.exists():
            return candidate, ver
    return None, "none"


def _claim_type_guess(section_name: str) -> str:
    sec = str(section_name or "").strip().lower()
    if sec in {"valuation", "risks", "business_overview", "risk_assessment"}:
        return "derived_aggregated"
    return "direct_factual_extraction"


def _priority_and_action(claim_type_guess: str, confidence: float) -> tuple[str, str]:
    if claim_type_guess == "direct_factual_extraction":
        if confidence < 0.75:
            return "P0", "核对高信任证据是否直接支撑并优先回填阈值误杀标签"
        if confidence <= 0.76:
            return "P1", "做边界复核，确认是否属于 near_threshold_boundary"
        return "P2", "常规抽检，确认无误后可保持 none 占位"
    if confidence < 0.75:
        return "P1", "按 derived 口径做人工语义复核，避免直接放宽规则"
    return "P2", "标记 derived 审核候选，优先级次于 direct 误杀排查"


@dataclass
class CaseRecord:
    case_id: str
    symbol: str
    period: str
    variant: str
    case_dir: Path
    claim_table: Path
    review_csv: Path | None
    review_version: str
    manifest_json: Path


def discover_cases(project_root: Path, eval_runs_dir: str = "data/evaluation/eval_v1/runs") -> List[CaseRecord]:
    root = (project_root / eval_runs_dir).resolve()
    if not root.exists():
        raise FileNotFoundError(f"eval_v1 runs 目录不存在: {root}")

    records: List[CaseRecord] = []
    for variant_dir in sorted(root.glob("*/*/*")):
        if not variant_dir.is_dir():
            continue
        symbol = variant_dir.parents[1].name
        period = variant_dir.parents[0].name
        variant = variant_dir.name
        case_id = f"{symbol}:{period}:{variant}"
        claim_table = variant_dir / "outputs" / "claim_table.json"
        reports_dir = variant_dir / "reports"
        review_csv, review_version = _pick_review_csv(reports_dir)
        manifest_json = variant_dir / "curated" / "real_data_manifest.json"
        records.append(
            CaseRecord(
                case_id=case_id,
                symbol=symbol,
                period=period,
                variant=variant,
                case_dir=variant_dir,
                claim_table=claim_table,
                review_csv=review_csv,
                review_version=review_version,
                manifest_json=manifest_json,
            )
        )
    return records


def run_review_coverage_expansion_v1(
    project_root: Path,
    eval_runs_dir: str = "data/evaluation/eval_v1/runs",
    output_dir: str = "artifacts/review_coverage_expansion_v1",
) -> Dict[str, object]:
    out_dir = (project_root / output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    records = discover_cases(project_root=project_root, eval_runs_dir=eval_runs_dir)
    if not records:
        raise ValueError("未发现 eval_v1 case。")

    case_inventory_rows: List[Dict[str, object]] = []
    review_queue_rows: List[Dict[str, object]] = []

    evaluable_cases = 0
    missing_review_cases = 0
    missing_claim_table_cases = 0

    for rec in records:
        has_claim_table = rec.claim_table.exists()
        has_review_csv = rec.review_csv is not None and rec.review_csv.exists()
        missing_components: List[str] = []
        if not has_claim_table:
            missing_components.append("claim_table")
            missing_claim_table_cases += 1
        if not has_review_csv:
            missing_components.append("review_csv")
            missing_review_cases += 1
        if not rec.manifest_json.exists():
            missing_components.append("manifest_json")
        is_evaluable = has_claim_table and has_review_csv
        if is_evaluable:
            evaluable_cases += 1

        case_inventory_rows.append(
            {
                "company_or_case": rec.symbol,
                "period": rec.period,
                "case_id": rec.case_id,
                "variant": rec.variant,
                "has_claim_table": has_claim_table,
                "has_review_csv": has_review_csv,
                "review_version": rec.review_version,
                "is_evaluable": is_evaluable,
                "missing_components": "|".join(missing_components) if missing_components else "none",
            }
        )

        if has_claim_table and not has_review_csv:
            claims = list(_read_json(rec.claim_table))
            for claim in claims:
                claim_id = str(claim.get("claim_id", ""))
                claim_text = str(claim.get("claim_text", ""))
                section_name = str(claim.get("section_name", ""))
                confidence = float(claim.get("confidence", 0.0))
                evidence_ids = [str(x) for x in list(claim.get("evidence_ids", []))]
                guess = _claim_type_guess(section_name)
                priority, action = _priority_and_action(guess, confidence)
                review_queue_rows.append(
                    {
                        "case_id": rec.case_id,
                        "claim_id": claim_id,
                        "claim_text": claim_text,
                        "claim_type_guess": guess,
                        "confidence": round(confidence, 4),
                        "evidence_ids": json.dumps(evidence_ids, ensure_ascii=False),
                        "priority": priority,
                        "recommended_review_action": action,
                    }
                )

    review_template_rows: List[Dict[str, object]] = []
    for row in review_queue_rows:
        review_template_rows.append(
            {
                "case_id": row["case_id"],
                "claim_id": row["claim_id"],
                "claim_text": row["claim_text"],
                "claim_type_guess": row["claim_type_guess"],
                "confidence": row["confidence"],
                "root_cause_primary": "",
                "root_cause_secondary": "",
                "failure_stage": "verification",
                "evidence_issue_type": "",
                "numeric_issue_type": "",
                "verifier_issue_type": "",
                "is_systematic": "",
                "fix_owner": "evaluation",
                "proposed_fix": "",
                "confidence_after_review": "",
                "reviewer": "",
                "review_date": "",
                "notes": "",
            }
        )

    # Sort queue by priority then confidence asc (low conf first)
    prio_rank = {"P0": 0, "P1": 1, "P2": 2}
    review_queue_rows = sorted(review_queue_rows, key=lambda r: (prio_rank.get(str(r["priority"]), 9), float(r["confidence"])))
    review_template_rows = sorted(
        review_template_rows,
        key=lambda r: (prio_rank.get("P2", 9), float(r["confidence"])),  # template follows queue order after write below
    )
    # align template order with queue order by case/claim
    queue_order = {(r["case_id"], r["claim_id"]): i for i, r in enumerate(review_queue_rows)}
    review_template_rows = sorted(
        review_template_rows,
        key=lambda r: queue_order.get((r["case_id"], r["claim_id"]), 10**9),
    )

    coverage_summary = {
        "experiment_name": "review_coverage_expansion_v1",
        "case_inventory": {
            "total_case_count": len(records),
            "evaluable_case_count": evaluable_cases,
            "missing_review_case_count": missing_review_cases,
            "missing_claim_table_case_count": missing_claim_table_cases,
            "coverage_ratio": round(evaluable_cases / float(len(records)), 4) if records else 0.0,
        },
        "review_queue": {
            "total_queue_claims": len(review_queue_rows),
            "priority_counts": {
                "P0": sum(1 for r in review_queue_rows if r["priority"] == "P0"),
                "P1": sum(1 for r in review_queue_rows if r["priority"] == "P1"),
                "P2": sum(1 for r in review_queue_rows if r["priority"] == "P2"),
            },
            "direct_claims": sum(1 for r in review_queue_rows if r["claim_type_guess"] == "direct_factual_extraction"),
            "derived_claims": sum(1 for r in review_queue_rows if r["claim_type_guess"] == "derived_aggregated"),
        },
        "outputs": {
            "case_inventory_csv": str(out_dir / "case_inventory.csv"),
            "review_queue_csv": str(out_dir / "review_queue.csv"),
            "review_template_csv": str(out_dir / "review_template.csv"),
            "coverage_summary_json": str(out_dir / "coverage_summary.json"),
            "coverage_summary_md": str(out_dir / "coverage_summary.md"),
        },
    }

    _write_csv(
        out_dir / "case_inventory.csv",
        rows=case_inventory_rows,
        fieldnames=[
            "company_or_case",
            "period",
            "case_id",
            "variant",
            "has_claim_table",
            "has_review_csv",
            "review_version",
            "is_evaluable",
            "missing_components",
        ],
    )
    _write_csv(
        out_dir / "review_queue.csv",
        rows=review_queue_rows,
        fieldnames=[
            "case_id",
            "claim_id",
            "claim_text",
            "claim_type_guess",
            "confidence",
            "evidence_ids",
            "priority",
            "recommended_review_action",
        ],
    )
    _write_csv(
        out_dir / "review_template.csv",
        rows=review_template_rows,
        fieldnames=[
            "case_id",
            "claim_id",
            "claim_text",
            "claim_type_guess",
            "confidence",
            "root_cause_primary",
            "root_cause_secondary",
            "failure_stage",
            "evidence_issue_type",
            "numeric_issue_type",
            "verifier_issue_type",
            "is_systematic",
            "fix_owner",
            "proposed_fix",
            "confidence_after_review",
            "reviewer",
            "review_date",
            "notes",
        ],
    )

    (out_dir / "coverage_summary.json").write_text(json.dumps(coverage_summary, indent=2, ensure_ascii=False), encoding="utf-8")

    md_lines = [
        "# Review 覆盖扩展 v1 总结",
        "",
        "## 覆盖现状",
        "",
        f"- 总 case 数: {coverage_summary['case_inventory']['total_case_count']}",
        f"- 可评估 case 数: {coverage_summary['case_inventory']['evaluable_case_count']}",
        f"- 缺 review 的 case 数: {coverage_summary['case_inventory']['missing_review_case_count']}",
        f"- 缺 claim_table 的 case 数: {coverage_summary['case_inventory']['missing_claim_table_case_count']}",
        f"- 当前覆盖率: {coverage_summary['case_inventory']['coverage_ratio']}",
        "",
        "## 审核队列规模",
        "",
        f"- 待审 claim 总数: {coverage_summary['review_queue']['total_queue_claims']}",
        f"- P0: {coverage_summary['review_queue']['priority_counts']['P0']}",
        f"- P1: {coverage_summary['review_queue']['priority_counts']['P1']}",
        f"- P2: {coverage_summary['review_queue']['priority_counts']['P2']}",
        f"- direct factual: {coverage_summary['review_queue']['direct_claims']}",
        f"- derived/aggregated: {coverage_summary['review_queue']['derived_claims']}",
        "",
        "## 建议审核顺序",
        "",
        "- 第一优先级（P0）：direct factual 且 confidence < 0.75 的条目，优先识别阈值误杀。",
        "- 第二优先级（P1）：derived 低置信度条目与 direct 边界条目（约 0.75/0.76）。",
        "- 第三优先级（P2）：其余常规抽检条目。",
        "",
        "## 审核口径提示",
        "",
        "- direct factual：重点核对高信任证据是否直接支撑、数字是否一致。",
        "- derived/aggregated：重点做语义和口径复核，不应直接复用 direct 放宽规则。",
        "",
        "## 产物路径",
        "",
        f"- case_inventory.csv: {coverage_summary['outputs']['case_inventory_csv']}",
        f"- review_queue.csv: {coverage_summary['outputs']['review_queue_csv']}",
        f"- review_template.csv: {coverage_summary['outputs']['review_template_csv']}",
        f"- coverage_summary.json: {coverage_summary['outputs']['coverage_summary_json']}",
        f"- coverage_summary.md: {coverage_summary['outputs']['coverage_summary_md']}",
        "",
    ]
    (out_dir / "coverage_summary.md").write_text("\n".join(md_lines), encoding="utf-8")

    return coverage_summary
