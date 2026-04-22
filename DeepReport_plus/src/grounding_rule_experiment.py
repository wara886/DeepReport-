"""Grounding rule experiment v1 (standalone; no baseline mutation)."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_str(value: object) -> str:
    return str(value or "").strip()


def _pick(d: Dict[str, object], keys: Iterable[str], default: str = "") -> str:
    for k in keys:
        if k in d and str(d[k]).strip():
            return str(d[k]).strip()
    return default


@dataclass
class ExperimentPaths:
    claim_table: Path
    review_csv: Path
    manifest_json: Path
    output_dir: Path
    verification_report: Path | None = None


def auto_discover_paths(project_root: Path) -> ExperimentPaths:
    review_candidates = sorted(project_root.glob("data/evaluation/**/claim_review_backfill_v2.csv"))
    if not review_candidates:
        raise FileNotFoundError("未找到 claim_review_backfill_v2.csv，请通过命令行参数显式传入。")
    review_csv = review_candidates[0]

    case_root = review_csv.parents[1]  # .../<case>/reports/claim_review_backfill_v2.csv
    claim_table = case_root / "outputs" / "claim_table.json"
    manifest_json = case_root / "curated" / "real_data_manifest.json"
    verification = case_root / "outputs" / "verification_report.json"

    if not claim_table.exists():
        raise FileNotFoundError(f"claim_table.json 不存在: {claim_table}")
    if not manifest_json.exists():
        raise FileNotFoundError(f"real_data_manifest.json 不存在: {manifest_json}")

    return ExperimentPaths(
        claim_table=claim_table,
        review_csv=review_csv,
        manifest_json=manifest_json,
        output_dir=project_root / "artifacts" / "grounding_rule_experiment_v1",
        verification_report=verification if verification.exists() else None,
    )


def _load_review_rows(path: Path) -> Dict[str, Dict[str, str]]:
    with path.open("r", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    out: Dict[str, Dict[str, str]] = {}
    for row in rows:
        item = dict(row)
        claim_id = _pick(item, ["claim_id", "claimId", "id"])
        if claim_id:
            out[claim_id] = {k: str(v) for k, v in item.items()}
    return out


def _load_evidence_map(path: Path) -> Dict[str, Dict[str, object]]:
    rows = list(_read_json(path))
    out: Dict[str, Dict[str, object]] = {}
    for r in rows:
        item = dict(r)
        eid = _pick(item, ["sample_id", "evidence_id", "id"])
        if eid:
            out[eid] = item
    return out


def _format_number_candidates(value: float) -> List[str]:
    return [
        str(value),
        f"{value:.0f}",
        f"{value:.1f}",
        f"{value:.2f}",
    ]


def _numbers_in_text(numeric_values: Dict[str, object], text: str) -> bool:
    hay = str(text)
    for v in numeric_values.values():
        num = _safe_float(v, default=float("nan"))
        if num != num:  # NaN
            return False
        if not any(c in hay for c in _format_number_candidates(num)):
            return False
    return True


def _is_high_trust(evidence_ids: List[str], evidence_map: Dict[str, Dict[str, object]]) -> bool:
    if not evidence_ids:
        return False
    trust_levels = []
    for eid in evidence_ids:
        evidence = evidence_map.get(eid, {})
        trust_levels.append(_normalize_str(evidence.get("trust_level")).lower())
    return any(t == "high" for t in trust_levels)


def _classify_claim_type(claim: Dict[str, object], review_row: Dict[str, str] | None) -> str:
    if review_row:
        primary = _normalize_str(review_row.get("root_cause_primary")).lower()
        if primary == "requires_manual_semantic_review":
            return "derived_aggregated"
    section = _normalize_str(claim.get("section_name")).lower()
    if section in {"valuation", "risks", "business_overview"}:
        return "derived_aggregated"
    return "direct_factual_extraction"


def _build_evidence_lookup_rows(
    evidence_ids: List[str],
    evidence_map: Dict[str, Dict[str, object]],
    manifest_json_path: Path,
) -> List[Dict[str, str]]:
    curated_dir = manifest_json_path.parent
    out: List[Dict[str, str]] = []
    for eid in sorted(set(evidence_ids)):
        item = evidence_map.get(eid, {})
        source_type = _normalize_str(item.get("source_type")) or "unknown"
        source_file = curated_dir / f"{source_type}.parquet"
        if not source_file.exists():
            source_file = manifest_json_path
        out.append(
            {
                "evidence_id": eid,
                "source_file": str(source_file),
                "text_preview": _normalize_str(item.get("content"))[:160],
                "source_type": source_type,
            }
        )
    return out


def run_grounding_rule_experiment(paths: ExperimentPaths) -> Dict[str, object]:
    claims = list(_read_json(paths.claim_table))
    review_by_claim = _load_review_rows(paths.review_csv)
    evidence_map = _load_evidence_map(paths.manifest_json)
    output_dir = paths.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    threshold = 0.75
    per_claim_rows: List[Dict[str, object]] = []
    all_evidence_ids: List[str] = []

    for raw in claims:
        claim = dict(raw)
        claim_id = _pick(claim, ["claim_id", "claimId", "id"])
        review = review_by_claim.get(claim_id, {})

        confidence = _safe_float(claim.get("confidence"), 0.0)
        evidence_ids = [str(x) for x in list(claim.get("evidence_ids", []))]
        numeric_values = dict(claim.get("numeric_values", {}))
        claim_text = _normalize_str(claim.get("claim_text"))
        claim_type = _classify_claim_type(claim, review if review else None)

        baseline_grounded = confidence >= threshold
        high_trust = _is_high_trust(evidence_ids, evidence_map)
        claim_numeric_aligned = bool(numeric_values) and _numbers_in_text(numeric_values, claim_text)
        evidence_numeric_aligned = False
        for eid in evidence_ids:
            evidence_numeric_aligned = evidence_numeric_aligned or _numbers_in_text(
                numeric_values, _normalize_str(evidence_map.get(eid, {}).get("content"))
            )
        direct_supported = high_trust and claim_numeric_aligned and evidence_numeric_aligned

        if claim_type == "direct_factual_extraction":
            rule_aware_grounded = baseline_grounded or direct_supported
            branch = "direct_supported_branch" if (not baseline_grounded and direct_supported) else "direct_confidence_branch"
        else:
            # Derived/Aggregated claims keep strict baseline branch in v1.
            rule_aware_grounded = baseline_grounded
            branch = "derived_strict_branch"

        changed = bool(rule_aware_grounded) != bool(baseline_grounded)
        status_transition = "unchanged"
        if (not baseline_grounded) and rule_aware_grounded:
            status_transition = "false_negative_to_pass"
        elif baseline_grounded and (not rule_aware_grounded):
            status_transition = "pass_to_reject"

        all_evidence_ids.extend(evidence_ids)
        per_claim_rows.append(
            {
                "claim_id": claim_id,
                "section_name": _normalize_str(claim.get("section_name")),
                "claim_type": claim_type,
                "confidence": round(confidence, 4),
                "baseline_threshold": threshold,
                "baseline_is_grounded": bool(baseline_grounded),
                "rule_aware_is_grounded": bool(rule_aware_grounded),
                "changed": changed,
                "status_transition": status_transition,
                "high_trust_source": bool(high_trust),
                "direct_literal_alignment": bool(claim_numeric_aligned),
                "numeric_consistent_with_evidence": bool(evidence_numeric_aligned),
                "direct_supported": bool(direct_supported),
                "rule_branch": branch,
                "review_root_cause_primary": _normalize_str(review.get("root_cause_primary")),
            }
        )

    direct_rows = [r for r in per_claim_rows if r["claim_type"] == "direct_factual_extraction"]
    derived_rows = [r for r in per_claim_rows if r["claim_type"] == "derived_aggregated"]
    false_negative_to_pass = [r["claim_id"] for r in per_claim_rows if r["status_transition"] == "false_negative_to_pass"]
    derived_changed = [r["claim_id"] for r in derived_rows if bool(r["changed"])]

    reviewed_threshold_false_negative = {
        cid
        for cid, r in review_by_claim.items()
        if _normalize_str(r.get("root_cause_primary")).lower() == "threshold_too_strict"
    }
    newly_accepted_set = set(false_negative_to_pass)
    suspicious_new_accept = sorted(newly_accepted_set - reviewed_threshold_false_negative)

    direct_rate_baseline = (
        sum(1 for r in direct_rows if bool(r["baseline_is_grounded"])) / float(len(direct_rows)) if direct_rows else 0.0
    )
    direct_rate_rule_aware = (
        sum(1 for r in direct_rows if bool(r["rule_aware_is_grounded"])) / float(len(direct_rows)) if direct_rows else 0.0
    )
    direct_delta = direct_rate_rule_aware - direct_rate_baseline

    if suspicious_new_accept:
        fp_risk = "\u5b58\u5728\u6f5c\u5728\u5047\u9633\u6027\u98ce\u9669\uff1a\u6709\u65b0\u901a\u8fc7\u6761\u76ee\u672a\u5728\u4eba\u5ba1\u9608\u503c\u8bef\u6740\u540d\u5355\u4e2d\u3002"
        fp_risk_flag = True
    else:
        fp_risk = "\u672a\u89c1\u660e\u663e\u5047\u9633\u6027\u98ce\u9669\uff1a\u65b0\u589e\u901a\u8fc7\u6761\u76ee\u5747\u843d\u5728\u4eba\u5ba1\u786e\u8ba4\u7684\u9608\u503c\u8bef\u6740\u96c6\u5408\u5185\u3002"
        fp_risk_flag = False

    enough_for_canary = False
    canary_reason = "\u5f53\u524d\u4ec5\u8986\u76d6 AAPL \u5355 case\uff0c\u6837\u672c\u8303\u56f4\u4e0d\u8db3\uff0c\u4e0d\u5efa\u8bae\u76f4\u63a5\u8fdb\u5165\u5927\u8303\u56f4\u7070\u5ea6\u3002"

    summary = {
        "experiment_name": "grounding_rule_experiment_v1",
        "input_paths": {
            "claim_table": str(paths.claim_table),
            "review_csv": str(paths.review_csv),
            "manifest_json": str(paths.manifest_json),
            "verification_report": str(paths.verification_report) if paths.verification_report else "",
        },
        "rules": {
            "baseline": "is_grounded = confidence >= 0.75",
            "rule_aware": "direct_factual_extraction: baseline OR direct_supported; derived_aggregated: baseline only",
            "direct_supported_definition": "high_trust_source AND direct_literal_alignment AND numeric_consistent_with_evidence",
        },
        "total_claims": len(per_claim_rows),
        "direct_claim_count": len(direct_rows),
        "derived_claim_count": len(derived_rows),
        "false_negative_to_pass_claim_ids": false_negative_to_pass,
        "direct_grounded_rate": {
            "baseline": round(direct_rate_baseline, 4),
            "rule_aware": round(direct_rate_rule_aware, 4),
            "delta": round(direct_delta, 4),
        },
        "derived_stability": {
            "changed_count": len(derived_changed),
            "changed_claim_ids": derived_changed,
            "stable": len(derived_changed) == 0,
        },
        "false_positive_risk": {
            "flag": fp_risk_flag,
            "message": fp_risk,
            "suspicious_new_accept_claim_ids": suspicious_new_accept,
        },
        "canary_readiness": {
            "ready": enough_for_canary,
            "reason": canary_reason,
        },
        "outputs": {
            "summary_json": str(output_dir / "summary.json"),
            "summary_md": str(output_dir / "summary.md"),
            "per_claim_csv": str(output_dir / "per_claim.csv"),
            "evidence_lookup_csv": str(output_dir / "evidence_lookup.csv"),
        },
    }

    # per-claim csv
    per_claim_csv = output_dir / "per_claim.csv"
    with per_claim_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(per_claim_rows[0].keys()) if per_claim_rows else ["claim_id"])
        writer.writeheader()
        if per_claim_rows:
            writer.writerows(per_claim_rows)

    # evidence lookup csv
    evidence_rows = _build_evidence_lookup_rows(all_evidence_ids, evidence_map=evidence_map, manifest_json_path=paths.manifest_json)
    evidence_csv = output_dir / "evidence_lookup.csv"
    with evidence_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["evidence_id", "source_file", "text_preview", "source_type"])
        writer.writeheader()
        writer.writerows(evidence_rows)

    # summary json
    summary_json = output_dir / "summary.json"
    summary_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    # summary md
    summary_md = output_dir / "summary.md"
    lines = [
        "# Grounding \u89c4\u5219\u5b9e\u9a8c v1 \u603b\u7ed3",
        "",
        "## \u6837\u672c\u8303\u56f4",
        "",
        "- \u5f53\u524d\u6837\u672c\u4ec5\u5305\u542b AAPL \u5355 case\uff08\u7ed3\u8bba\u4ec5\u5bf9\u5f53\u524d\u6837\u672c\u6210\u7acb\uff0c\u4e0d\u5916\u63a8\u6cdb\u5316\uff09\u3002",
        "",
        "## \u95ee\u9898 1\uff1a\u54ea\u4e9b\u6761\u76ee\u4ece\u8bef\u6740\u53d8\u6210\u901a\u8fc7",
        "",
        f"- \u7531\u8bef\u6740\u8f6c\u901a\u8fc7\uff08false_negative_to_pass\uff09: {false_negative_to_pass}",
        "",
        "## \u95ee\u9898 2\uff1adirect factual claims \u7684 grounded rate \u63d0\u5347\u591a\u5c11",
        "",
        f"- baseline: {round(direct_rate_baseline, 4)}",
        f"- rule-aware: {round(direct_rate_rule_aware, 4)}",
        f"- \u63d0\u5347\uff08delta\uff09: {round(direct_delta, 4)}",
        "",
        "## \u95ee\u9898 3\uff1aderived claims \u662f\u5426\u4fdd\u6301\u7a33\u5b9a",
        "",
        f"- derived \u53d8\u52a8\u6761\u76ee\u6570: {len(derived_changed)}",
        f"- derived \u53d8\u52a8\u6761\u76ee: {derived_changed}",
        "",
        "## \u95ee\u9898 4\uff1a\u662f\u5426\u51fa\u73b0\u660e\u663e\u5047\u9633\u6027\u98ce\u9669",
        "",
        f"- \u5224\u65ad: {fp_risk}",
        f"- \u53ef\u7591\u65b0\u589e\u901a\u8fc7\u6761\u76ee: {suspicious_new_accept}",
        "",
        "## \u95ee\u9898 5\uff1a\u5f53\u524d\u662f\u5426\u8db3\u4ee5\u8fdb\u5165\u66f4\u5927\u8303\u56f4\u7070\u5ea6",
        "",
        f"- \u7ed3\u8bba: {enough_for_canary}",
        f"- \u539f\u56e0: {canary_reason}",
        "",
        "## \u98ce\u9669\u4e0e\u5c40\u9650",
        "",
        "- \u5f53\u524d\u4ec5\u4e3a\u5355\u6837\u672c\u79bb\u7ebf\u5b9e\u9a8c\uff0c\u4e0d\u80fd\u4ee3\u8868\u8de8\u884c\u4e1a\u3001\u8de8\u65f6\u671f\u7a33\u5b9a\u6027\u3002",
        "- direct_supported \u4ecd\u4f9d\u8d56\u5b57\u9762\u5bf9\u9f50\u4e0e\u6570\u5b57\u5339\u914d\uff0c\u672a\u8986\u76d6\u590d\u6742\u8bed\u4e49\u7b49\u4ef7\u8868\u8fbe\u3002",
        "- derived/aggregated \u5206\u652f\u4ecd\u504f\u4fdd\u5b88\uff0c\u9700\u8981\u540e\u7eed\u4eba\u5de5\u8bed\u4e49\u89c4\u5219\u7ec6\u5316\u3002",
        "",
    ]
    summary_md.write_text("\n".join(lines), encoding="utf-8")

    return summary
