"""Summarize Stage12 evaluation artifacts into regression_v1 outputs."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


SOURCE_HINTS = ("financials", "filings", "news", "company_profile", "market")


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


def _mean(values: Iterable[float]) -> float:
    vals = list(values)
    if not vals:
        return 0.0
    return round(sum(vals) / float(len(vals)), 4)


def _extract_source_tag(text: str) -> str:
    lower = text.lower()
    for hint in SOURCE_HINTS:
        if hint in lower:
            return hint
    return ""


def _topk_hit(reranked_ids: List[str], gold_evidence_ids: List[str], k: int, source_types: List[str] | None = None) -> bool:
    if (not reranked_ids and not source_types) or not gold_evidence_ids:
        return False
    gold_tags = {_extract_source_tag(x) for x in gold_evidence_ids}
    gold_tags.discard("")
    if not gold_tags:
        return False
    if source_types:
        for source in source_types[:k]:
            if _extract_source_tag(str(source)) in gold_tags:
                return True
    for rid in reranked_ids[:k]:
        if _extract_source_tag(str(rid)) in gold_tags:
            return True
    return False


def _flatten_numeric_errors(detail: Dict[str, int]) -> str:
    tags = [f"{k}:{v}" for k, v in sorted(detail.items()) if int(v) > 0]
    return "|".join(tags) if tags else "none"


def _select_primary_rows(per_report_rows: List[Dict[str, object]], primary_variant: str) -> List[Dict[str, object]]:
    preferred = [r for r in per_report_rows if str(r.get("variant_id", "")) == primary_variant]
    if preferred:
        return preferred
    return per_report_rows


def _bucket_score(value: float) -> str:
    if value < 0.2:
        return "[0.0,0.2)"
    if value < 0.4:
        return "[0.2,0.4)"
    if value < 0.6:
        return "[0.4,0.6)"
    if value < 0.8:
        return "[0.6,0.8)"
    return "[0.8,1.0]"


def _count_buckets(values: Iterable[float]) -> Dict[str, int]:
    counts = {
        "[0.0,0.2)": 0,
        "[0.2,0.4)": 0,
        "[0.4,0.6)": 0,
        "[0.6,0.8)": 0,
        "[0.8,1.0]": 0,
    }
    for value in values:
        key = _bucket_score(float(value))
        counts[key] = counts.get(key, 0) + 1
    return counts


def build_regression_v1_outputs(
    eval_output_root: str | Path = "data/evaluation/stage12a",
    eval_case_path: str | Path = "data/eval_v1/cases.jsonl",
    report_root: str | Path = "reports/eval_v1",
    primary_variant: str = "bm25_real_writer",
) -> Dict[str, object]:
    """Build summary.json/summary.md/per_case.csv from stage12 artifacts."""

    eval_root = Path(eval_output_root)
    report_dir = Path(report_root)
    report_dir.mkdir(parents=True, exist_ok=True)

    per_report_rows = _read_jsonl(eval_root / "per_report_metrics.jsonl")
    numeric_rows = _read_jsonl(eval_root / "per_case_numeric_audit_v1.jsonl")
    eval_cases = _read_jsonl(Path(eval_case_path))
    case_lookup = {str(c.get("case_id", "")): c for c in eval_cases}

    numeric_lookup: Dict[Tuple[str, str], Dict[str, object]] = {}
    for row in numeric_rows:
        key = (str(row.get("case_id", "")), str(row.get("variant_id", "")))
        numeric_lookup[key] = row

    chosen_rows = _select_primary_rows(per_report_rows, primary_variant=primary_variant)
    augmented_rows: List[Dict[str, object]] = []
    per_case_csv = report_dir / "per_case.csv"
    with per_case_csv.open("w", encoding="utf-8", newline="") as fh:
        headers = [
            "case_id",
            "task_type",
            "variant_id",
            "evidence_coverage",
            "claim_grounded_rate",
            "numeric_accuracy",
            "supported_numeric_claims",
            "numeric_claims",
            "writer_fallback_triggered",
            "fallback_reason",
            "top1_evidence_hit",
            "top3_evidence_hit",
            "error_taxonomy",
        ]
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()
        for row in chosen_rows:
            case_id = str(row.get("case_id", ""))
            variant_id = str(row.get("variant_id", ""))
            task_type = str(row.get("task_type", "unknown"))
            case = case_lookup.get(case_id, {})
            numeric = numeric_lookup.get((case_id, variant_id), {})
            numeric_claims = int(numeric.get("numeric_claims", 0))
            supported = int(numeric.get("supported_numeric_claims", 0))
            numeric_accuracy = round(float(supported) / float(numeric_claims), 4) if numeric_claims else 0.0
            fallback_reason = str(row.get("writer_error_message", "")).strip() or "none"
            topk_ids = [str(x) for x in list(row.get("reranked_topk_ids", []))]
            topk_source_types = [str(x) for x in list(row.get("reranked_topk_source_types", []))]
            gold_ids = [str(x) for x in list(case.get("gold_evidence_ids", []))]
            top1 = _topk_hit(topk_ids, gold_ids, k=1, source_types=topk_source_types)
            top3 = _topk_hit(topk_ids, gold_ids, k=3, source_types=topk_source_types)
            taxonomy = _flatten_numeric_errors(dict(numeric.get("error_breakdown", {})))
            if bool(row.get("writer_fallback_triggered", False)):
                taxonomy = taxonomy if taxonomy != "none" else "writer_fallback"
            writer.writerow(
                {
                    "case_id": case_id,
                    "task_type": task_type,
                    "variant_id": variant_id,
                    "evidence_coverage": round(float(row.get("evidence_coverage", 0.0)), 4),
                    "claim_grounded_rate": round(float(row.get("current_verifier_pass_ratio", 0.0)), 4),
                    "numeric_accuracy": numeric_accuracy,
                    "supported_numeric_claims": supported,
                    "numeric_claims": numeric_claims,
                    "writer_fallback_triggered": bool(row.get("writer_fallback_triggered", False)),
                    "fallback_reason": fallback_reason,
                    "top1_evidence_hit": top1,
                    "top3_evidence_hit": top3,
                    "error_taxonomy": taxonomy,
                }
            )
            augmented_rows.append(
                {
                    "case_id": case_id,
                    "task_type": task_type,
                    "variant_id": variant_id,
                    "claim_grounded_rate": round(float(row.get("current_verifier_pass_ratio", 0.0)), 4),
                    "numeric_accuracy": numeric_accuracy,
                    "writer_fallback_triggered": bool(row.get("writer_fallback_triggered", False)),
                    "error_taxonomy": taxonomy,
                    "report_md_path": str(dict(row.get("artifacts", {})).get("report_md", "")),
                    "verification_report_path": str(dict(row.get("artifacts", {})).get("verification_report", "")),
                    "claim_table_path": str(dict(row.get("artifacts", {})).get("claim_table", "")),
                }
            )

    evidence_coverage = _mean(float(r.get("evidence_coverage", 0.0)) for r in chosen_rows)
    claim_grounded_rate = _mean(float(r.get("current_verifier_pass_ratio", 0.0)) for r in chosen_rows)
    fallback_rate = _mean(1.0 if bool(r.get("writer_fallback_triggered", False)) else 0.0 for r in chosen_rows)
    top1_rate = _mean(
        1.0
        if _topk_hit(
            [str(x) for x in list(r.get("reranked_topk_ids", []))],
            [str(x) for x in list(case_lookup.get(str(r.get("case_id", "")), {}).get("gold_evidence_ids", []))],
            k=1,
            source_types=[str(x) for x in list(r.get("reranked_topk_source_types", []))],
        )
        else 0.0
        for r in chosen_rows
    )
    top3_rate = _mean(
        1.0
        if _topk_hit(
            [str(x) for x in list(r.get("reranked_topk_ids", []))],
            [str(x) for x in list(case_lookup.get(str(r.get("case_id", "")), {}).get("gold_evidence_ids", []))],
            k=3,
            source_types=[str(x) for x in list(r.get("reranked_topk_source_types", []))],
        )
        else 0.0
        for r in chosen_rows
    )

    numeric_total = 0
    numeric_supported = 0
    fallback_numeric_total = 0
    fallback_numeric_supported = 0
    error_counter: Dict[str, int] = {}
    for row in chosen_rows:
        key = (str(row.get("case_id", "")), str(row.get("variant_id", "")))
        numeric = numeric_lookup.get(key, {})
        numeric_total += int(numeric.get("numeric_claims", 0))
        numeric_supported += int(numeric.get("supported_numeric_claims", 0))
        for err, count in dict(numeric.get("error_breakdown", {})).items():
            error_counter[str(err)] = error_counter.get(str(err), 0) + int(count)
        if bool(row.get("writer_fallback_triggered", False)):
            fallback_numeric_total += int(numeric.get("numeric_claims", 0))
            fallback_numeric_supported += int(numeric.get("supported_numeric_claims", 0))
    numeric_accuracy = round(float(numeric_supported) / float(numeric_total), 4) if numeric_total else 0.0
    fallback_numeric_accuracy = (
        round(float(fallback_numeric_supported) / float(fallback_numeric_total), 4) if fallback_numeric_total else None
    )

    summary = {
        "report_name": "regression_v1",
        "primary_variant": primary_variant,
        "sample_count": len(chosen_rows),
        "evidence_coverage": evidence_coverage,
        "claim_grounded_rate": claim_grounded_rate,
        "numeric_accuracy": numeric_accuracy,
        "fallback_rate": fallback_rate,
        "fallback_numeric_accuracy": fallback_numeric_accuracy,
        "top1_evidence_hit_rate": top1_rate,
        "top3_evidence_hit_rate": top3_rate,
        "per_case_error_taxonomy": error_counter,
        "sources": {
            "eval_output_root": str(eval_root),
            "eval_case_path": str(eval_case_path),
        },
        "outputs": {
            "summary_json": str(report_dir / "summary.json"),
            "summary_md": str(report_dir / "summary.md"),
            "per_case_csv": str(per_case_csv),
            "spot_check_10_csv": str(report_dir / "spot_check_10.csv"),
            "spot_check_10_md": str(report_dir / "spot_check_10.md"),
            "error_buckets_json": str(report_dir / "error_buckets.json"),
        },
    }

    error_buckets = {
        "claim_grounded_rate_buckets": _count_buckets(float(r.get("claim_grounded_rate", 0.0)) for r in augmented_rows),
        "numeric_accuracy_buckets": _count_buckets(float(r.get("numeric_accuracy", 0.0)) for r in augmented_rows),
        "low_grounded_cases": [
            str(r.get("case_id", ""))
            for r in sorted(augmented_rows, key=lambda x: float(x.get("claim_grounded_rate", 0.0)))
            if float(r.get("claim_grounded_rate", 0.0)) < 0.6
        ][:20],
        "low_numeric_cases": [
            str(r.get("case_id", ""))
            for r in sorted(augmented_rows, key=lambda x: float(x.get("numeric_accuracy", 0.0)))
            if float(r.get("numeric_accuracy", 0.0)) < 0.8
        ][:20],
    }
    (report_dir / "error_buckets.json").write_text(json.dumps(error_buckets, indent=2, ensure_ascii=False), encoding="utf-8")

    spot_candidates = sorted(
        augmented_rows,
        key=lambda x: (float(x.get("claim_grounded_rate", 0.0)), float(x.get("numeric_accuracy", 0.0))),
    )[:10]
    with (report_dir / "spot_check_10.csv").open("w", encoding="utf-8", newline="") as fh:
        headers = [
            "case_id",
            "task_type",
            "claim_grounded_rate",
            "numeric_accuracy",
            "writer_fallback_triggered",
            "error_taxonomy",
            "report_md_path",
            "verification_report_path",
            "claim_table_path",
        ]
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()
        for row in spot_candidates:
            writer.writerow({k: row.get(k, "") for k in headers})
    spot_lines = [
        "# Spot Check 10 Cases",
        "",
        "优先按 claim_grounded_rate 和 numeric_accuracy 最差案例抽检。",
        "",
    ]
    for idx, row in enumerate(spot_candidates, start=1):
        spot_lines.append(
            f"{idx}. {row['case_id']} | task={row['task_type']} | grounded={row['claim_grounded_rate']} | numeric={row['numeric_accuracy']} | fallback={row['writer_fallback_triggered']}"
        )
        spot_lines.append(f"   - report: {row['report_md_path']}")
        spot_lines.append(f"   - verifier: {row['verification_report_path']}")
        spot_lines.append(f"   - claim_table: {row['claim_table_path']}")
    (report_dir / "spot_check_10.md").write_text("\n".join(spot_lines), encoding="utf-8")

    (report_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "# regression_v1 Summary",
        "",
        f"- primary_variant: {summary['primary_variant']}",
        f"- sample_count: {summary['sample_count']}",
        f"- evidence_coverage: {summary['evidence_coverage']}",
        f"- claim_grounded_rate: {summary['claim_grounded_rate']}",
        f"- numeric_accuracy: {summary['numeric_accuracy']}",
        f"- fallback_rate: {summary['fallback_rate']}",
        f"- fallback_numeric_accuracy: {summary['fallback_numeric_accuracy']}",
        f"- top1_evidence_hit_rate: {summary['top1_evidence_hit_rate']}",
        f"- top3_evidence_hit_rate: {summary['top3_evidence_hit_rate']}",
        "",
        "## Error Taxonomy",
        "",
    ]
    if error_counter:
        for key, value in sorted(error_counter.items()):
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- none")
    (report_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    return summary
