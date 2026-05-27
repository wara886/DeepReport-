"""Formal frozen-snapshot benchmark runner and metric contract.

This module is intentionally offline with respect to evidence. Model calls may
be configured, but every variant receives evidence only from the validated
snapshot manifest.
"""

from __future__ import annotations

from collections import Counter
import csv
from html import escape
import json
from pathlib import Path
import re
from typing import Any, Callable, Dict, Iterable, List

from src.agents.multi_agent_orchestrator import MultiAgentOrchestrator
from src.agents.verifier import Verifier
from src.evaluation.benchmark_metrics import deterministic_delivery_checks
from src.evaluation.frozen_snapshot import (
    load_formal_benchmark_config,
    load_snapshot_case_evidence,
    snapshot_evidence_ids,
    validate_frozen_snapshot,
)
from src.evaluation.report_quality import evaluate_report_quality_from_paths, write_quality_outputs_for_paths
from src.models import ModelAdapter
from src.report.citation_manager import build_citation_artifacts
from src.retrieval.bm25_index import BM25Index
from src.retrieval.evidence_store import EvidenceRecord
from src.schemas.claim import ClaimItem
from src.search import SearchManager


TRACEABLE_V1_LABEL = "Traceable Claim Rate v1"
CRITICAL_CLAIM_TYPES = (
    "revenue",
    "profit",
    "cash_flow",
    "margin",
    "valuation",
    "peer_comparison",
    "risk",
    "investment_rationale",
)
VARIANT_IDS = ("direct_llm", "single_agent_rag", "multi_agent_rag")
ONE_SHOT_SYSTEM_PROMPT = """You generate a company research report for a formal benchmark.
Use only supplied frozen evidence. Return JSON with `claims` and `markdown`.
Each critical claim must include `is_critical: true` and one `critical_claim_type`
from revenue, profit, cash_flow, margin, valuation, peer_comparison, risk,
investment_rationale. Cite evidence in markdown as [evidence_id]. Do not browse.
Return compact valid JSON: at most 8 claims, and Markdown no longer than 1500
characters with only the five required sections and up to two bullets per section."""


def formal_traceable_claim_metrics(
    claims: List[Dict[str, Any]],
    citations: List[Dict[str, Any]],
    frozen_evidence_ids: set[str],
    numeric_audit: Dict[str, Any],
) -> Dict[str, Any]:
    """Evaluate the explicit formal traceability contract."""

    critical = [
        row
        for row in claims
        if row.get("is_critical") is True and str(row.get("critical_claim_type") or "") in CRITICAL_CLAIM_TYPES
    ]
    audit_by_claim = {
        str(row.get("claim_id") or ""): row
        for row in numeric_audit.get("claims", [])
        if isinstance(row, dict) and str(row.get("claim_id") or "")
    }
    traced: List[str] = []
    issues: List[Dict[str, str]] = []
    for index, claim in enumerate(critical, start=1):
        claim_id = str(claim.get("claim_id") or f"claim_{index:04d}")
        evidence_ids = [str(value) for value in claim.get("evidence_ids", []) if str(value)]
        valid_ids = [value for value in evidence_ids if value in frozen_evidence_ids]
        cited = any(
            str(row.get("evidence_id") or "") in valid_ids
            and row.get("used_in_report") is True
            and (not row.get("claim_ids") or claim_id in [str(value) for value in row.get("claim_ids", [])])
            for row in citations
            if isinstance(row, dict)
        )
        numeric_ok = True
        if isinstance(claim.get("numeric_values"), dict) and claim.get("numeric_values"):
            numeric_ok = bool(audit_by_claim.get(claim_id, {}).get("supported", False))
        errors = []
        if not valid_ids:
            errors.append("evidence_not_in_snapshot")
        if not cited:
            errors.append("citation_not_used_in_report")
        if not numeric_ok:
            errors.append("numeric_audit_failed")
        if errors:
            issues.append({"claim_id": claim_id, "reason": ",".join(errors)})
        else:
            traced.append(claim_id)
    if not critical:
        issues.append({"claim_id": "", "reason": "no_explicit_critical_claims"})
    return {
        "label": TRACEABLE_V1_LABEL,
        "critical_claim_count": len(critical),
        "traceable_claim_count": len(traced),
        "rate": round(len(traced) / len(critical), 4) if critical else 0.0,
        "traceable_claim_ids": traced,
        "issues": issues,
    }


def run_formal_benchmark(
    config_path: str | Path = "configs/benchmark_formal18_fy2024.yaml",
    snapshot_root: str | Path | None = None,
    output_root: str | Path | None = None,
    model: Any | None = None,
    multi_agent_factory: Callable[..., Any] = MultiAgentOrchestrator,
    variant_ids: Iterable[str] | None = None,
    case_ids: Iterable[str] | None = None,
    reuse_existing: bool = False,
) -> Dict[str, Any]:
    """Run all three variants only when a complete frozen snapshot exists."""

    benchmark = load_formal_benchmark_config(config_path)
    snapshot = Path(snapshot_root or benchmark["snapshot_root"])
    validation = validate_frozen_snapshot(snapshot, require_complete=True)
    if not validation.get("valid"):
        raise ValueError("formal benchmark cannot run: " + "; ".join(validation.get("validation_issues", [])))
    out = Path(output_root or benchmark.get("output_root") or "bench/formal18_fy24")
    out.mkdir(parents=True, exist_ok=True)
    (out / "snapshot_validation.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
    runtime_model = model or ModelAdapter.from_config(str(benchmark.get("model_config_path") or "configs/model_backends.yaml"))
    selected_variants = tuple(str(value) for value in variant_ids) if variant_ids else VARIANT_IDS
    unknown_variants = set(selected_variants) - set(VARIANT_IDS)
    if unknown_variants:
        raise ValueError(f"unknown formal variants requested: {sorted(unknown_variants)}")
    configured_case_ids = {str(item.get("case_id") or "") for item in benchmark["cases"] if isinstance(item, dict)}
    selected_cases = {str(value) for value in case_ids} if case_ids else configured_case_ids
    unknown_cases = selected_cases - configured_case_ids
    if unknown_cases:
        raise ValueError(f"unknown formal cases requested: {sorted(unknown_cases)}")

    records: List[Dict[str, Any]] = []
    existing_runs_path = out / "formal_runs.jsonl"
    if reuse_existing and existing_runs_path.exists():
        records.extend(
            row
            for row in _read_jsonl(existing_runs_path)
            if not (
                str(row.get("variant") or "") in selected_variants
                and str(row.get("case_id") or "") in selected_cases
            )
            and str(row.get("snapshot_sha256") or "") == str(validation.get("snapshot_sha256") or "")
        )
    snapshot_cases = {
        str(row.get("case_id") or ""): row
        for row in validation.get("cases", [])
        if isinstance(row, dict)
    }
    for case in [dict(item) for item in benchmark["cases"] if str(item.get("case_id") or "") in selected_cases]:
        evidence = load_snapshot_case_evidence(snapshot, str(case["case_id"]))
        allowed_ids = snapshot_evidence_ids(snapshot, str(case["case_id"]))
        for variant in [dict(item) for item in benchmark["variants"] if str(item.get("id") or "") in selected_variants]:
            records.append(
                _run_case_variant(
                    case=case,
                    variant=variant,
                    period=str(benchmark["period"]),
                    evidence=evidence,
                    frozen_evidence_ids=allowed_ids,
                    root=out,
                    model=runtime_model,
                    multi_agent_factory=multi_agent_factory,
                    dataset_version=str(validation.get("dataset_version") or ""),
                    snapshot_sha256=str(validation.get("snapshot_sha256") or ""),
                    snapshot_case_sha256=str(snapshot_cases.get(str(case["case_id"]), {}).get("sha256") or ""),
                )
            )
            _write_jsonl(out / "formal_runs_checkpoint.jsonl", records)
    summary = summarize_formal_records(records, total_case_count=len(benchmark["cases"]))
    paths = write_formal_outputs(out, records, summary, validation)
    return {**summary, "records": records, "paths": paths}


def summarize_formal_records(records: List[Dict[str, Any]], total_case_count: int) -> Dict[str, Any]:
    """Summarize fixed-denominator formal records by variant and market."""

    by_variant: Dict[str, Dict[str, Any]] = {}
    for variant in VARIANT_IDS:
        rows = [row for row in records if row.get("variant") == variant]
        by_variant[variant] = {
            "overall": _fixed_summary(rows),
            "by_market": {market: _fixed_summary([row for row in rows if row.get("market") == market]) for market in ("US", "HK", "CN-A")},
            "secondary": _secondary_summary(rows),
        }
    taxonomy: Counter[str] = Counter()
    for row in records:
        taxonomy.update(str(item) for item in row.get("failure_categories", []))
    return {
        "schema_version": "formal_benchmark.v1",
        "metric_scope": "traceable_claim_rate_v1",
        "case_count": total_case_count,
        "report_count": len(records),
        "variants": by_variant,
        "failure_counts": dict(taxonomy),
        "failure_counts_by_variant": {
            variant: dict(
                Counter(
                    str(category)
                    for row in records
                    if row.get("variant") == variant
                    for category in row.get("failure_categories", [])
                )
            )
            for variant in VARIANT_IDS
        },
    }


def write_formal_outputs(
    output_root: Path,
    records: List[Dict[str, Any]],
    summary: Dict[str, Any],
    snapshot_validation: Dict[str, Any],
) -> Dict[str, str]:
    """Write formal comparison artifacts."""

    overall_path = output_root / "formal_results_overall.csv"
    market_path = output_root / "formal_results_by_market.csv"
    secondary_path = output_root / "formal_secondary_metrics.csv"
    runs_path = output_root / "formal_runs.jsonl"
    failures_path = output_root / "formal_failures.csv"
    report_path = output_root / "formal_benchmark_report.md"
    with overall_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["variant", "delivery_pass_rate", "objective_quality_score", "traceable_claim_rate_v1"])
        writer.writeheader()
        for variant in VARIANT_IDS:
            values = summary["variants"][variant]["overall"]
            writer.writerow({"variant": variant, **values})
    with market_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["variant", "market", "delivery_pass_rate", "objective_quality_score", "traceable_claim_rate_v1"])
        writer.writeheader()
        for variant in VARIANT_IDS:
            for market in ("US", "HK", "CN-A"):
                writer.writerow({"variant": variant, "market": market, **summary["variants"][variant]["by_market"][market]})
    with secondary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "variant",
                "run_count",
                "evaluated_run_count",
                "runtime_or_model_failure_count",
                "delivery_failed_run_count",
                "critical_claim_count",
                "traceable_claim_count",
                "micro_traceable_claim_rate_v1",
            ],
        )
        writer.writeheader()
        for variant in VARIANT_IDS:
            writer.writerow({"variant": variant, **summary["variants"][variant]["secondary"]})
    runs_path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in records) + ("\n" if records else ""), encoding="utf-8")
    with failures_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["variant", "case_id", "market", "category", "detail"])
        writer.writeheader()
        for row in records:
            for category in row.get("failure_categories", []):
                writer.writerow(
                    {
                        "variant": row.get("variant", ""),
                        "case_id": row.get("case_id", ""),
                        "market": row.get("market", ""),
                        "category": category,
                        "detail": row.get("error", ""),
                    }
                )
    report_path.write_text(_render_formal_report(summary, snapshot_validation), encoding="utf-8")
    return {
        "overall_results": str(overall_path),
        "market_results": str(market_path),
        "secondary_metrics": str(secondary_path),
        "runs": str(runs_path),
        "failures": str(failures_path),
        "report": str(report_path),
    }


def _run_case_variant(
    case: Dict[str, Any],
    variant: Dict[str, Any],
    period: str,
    evidence: List[Dict[str, Any]],
    frozen_evidence_ids: set[str],
    root: Path,
    model: Any,
    multi_agent_factory: Callable[..., Any],
    dataset_version: str,
    snapshot_sha256: str,
    snapshot_case_sha256: str,
) -> Dict[str, Any]:
    variant_id = str(variant["id"])
    run_dir = root / "runs" / str(case["case_id"]) / variant_id
    outputs = run_dir / "outputs"
    reports = run_dir / "reports"
    outputs.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    base = {
        "case_id": str(case["case_id"]),
        "market": str(case["market"]),
        "company_name": str(case["company_name"]),
        "canonical_symbol": str(case["canonical_symbol"]),
        "variant": variant_id,
        "period": period,
        "outputs_dir": str(outputs),
        "reports_dir": str(reports),
        "dataset_version": dataset_version,
        "snapshot_sha256": snapshot_sha256,
        "snapshot_case_sha256": snapshot_case_sha256,
    }
    try:
        context = evidence if variant_id == "direct_llm" else _retrieve_context(evidence, case=case, topk=12)
        if variant_id in {"direct_llm", "single_agent_rag"}:
            claims, markdown, artifacts = _generate_one_shot(model, case=case, period=period, evidence=context, variant=variant_id)
        elif variant_id == "multi_agent_rag":
            claims, markdown, artifacts = _generate_multi_agent(
                model,
                case=case,
                period=period,
                evidence=evidence,
                run_dir=run_dir,
                outputs=outputs,
                reports=reports,
                orchestrator_factory=multi_agent_factory,
            )
            context = list(artifacts.get("context_evidence", context))
        else:
            raise ValueError(f"unknown formal variant: {variant_id}")
        claims = annotate_critical_claims(claims)
        numeric_audit = build_numeric_audit(claims, evidence)
        citation_payload = build_citation_artifacts(
            evidence_records=evidence,
            claims=claims,
            markdown=markdown,
            html=_html_report(markdown),
        )
        markdown = str(citation_payload["markdown"])
        verification = Verifier().verify(
            [ClaimItem.from_dict(row) for row in claims],
            markdown,
            evidence_records=evidence,
            expected_symbol=str(case["canonical_symbol"]),
            tables=artifacts.get("tables", []),
            valuation=artifacts.get("valuation", {}),
        )
        _write_json(outputs / "evidence.json", evidence)
        _write_json(outputs / "context_evidence.json", context)
        _write_json(outputs / "claims.json", claims)
        _write_json(outputs / "citations.json", citation_payload["citations"])
        _write_json(outputs / "numeric_audit.json", numeric_audit)
        _write_json(outputs / "verification_report.json", verification)
        _write_json(outputs / "financial_metrics.json", artifacts.get("financial_metrics", {}))
        _write_json(outputs / "tables.json", artifacts.get("tables", []))
        _write_json(outputs / "valuation_model.json", artifacts.get("valuation_model", {}))
        _write_json(outputs / "valuation_sensitivity.json", artifacts.get("valuation_sensitivity", {}))
        charts = list(artifacts.get("charts", [])) if isinstance(artifacts.get("charts"), list) else []
        chart_consistency = (
            dict(artifacts["chart_consistency"])
            if isinstance(artifacts.get("chart_consistency"), dict)
            else {"passed": True, "formal_no_chart_conflict": True}
        )
        _write_json(outputs / "charts.json", charts)
        _write_json(outputs / "chart_consistency.json", chart_consistency)
        _write_json(
            outputs / "run_summary.json",
            {
                "symbol": case["canonical_symbol"],
                "period": period,
                "model": getattr(model, "model_name", ""),
                "variant": variant_id,
                "entity_resolution": {"resolved_symbol": case["canonical_symbol"]},
                "frozen_evidence_only": True,
                "retrieval": "none" if variant_id == "direct_llm" else "bm25_frozen_snapshot",
                "orchestration": "multi_agent_orchestrator" if variant_id == "multi_agent_rag" else "one_generation_call",
            },
        )
        (reports / "report.md").write_text(markdown, encoding="utf-8")
        (reports / "report.html").write_text(str(citation_payload["html"]), encoding="utf-8")
        _write_json(reports / "report.json", {"claims": claims, "variant": variant_id, "period": period})
        quality = evaluate_report_quality_from_paths(outputs, reports, run_dir=run_dir)
        write_quality_outputs_for_paths(outputs, reports, quality)
        trace = formal_traceable_claim_metrics(
            claims=claims,
            citations=list(citation_payload["citations"]),
            frozen_evidence_ids=frozen_evidence_ids,
            numeric_audit=numeric_audit,
        )
        checks = deterministic_delivery_checks(
            case=case,
            summary={"symbol": case["canonical_symbol"], "entity_resolution": {"resolved_symbol": case["canonical_symbol"]}},
            report_text=markdown,
            citations=list(citation_payload["citations"]),
            quality=quality,
            verification=verification,
            chart_consistency=chart_consistency,
            traceability={"critical_claim_count": trace["critical_claim_count"], "traceable_claim_count": trace["traceable_claim_count"]},
        )
        delivery_keys = (
            "identity_resolved",
            "non_empty_executive_summary",
            "non_empty_risk",
            "non_empty_investment_conclusion",
            "citations_in_body",
            "three_statements_or_disclosed_gap",
            "valuation_or_reason",
            "chart_no_serious_conflict",
        )
        categories = []
        if trace["rate"] < 1.0:
            categories.append("citation_or_evidence_gap")
        if not all(checks.get(key, False) for key in delivery_keys):
            categories.append("delivery_requirement_failed")
        return {
            **base,
            "status": "evaluated",
            "delivery_pass": all(checks.get(key, False) for key in delivery_keys),
            "objective_quality_score": round(float(quality.get("total_score", 0.0)) * 100, 2),
            "traceable_claim_rate_v1": trace["rate"],
            "critical_claim_count": trace["critical_claim_count"],
            "traceable_claim_count": trace["traceable_claim_count"],
            "traceability_issues": trace["issues"],
            "failure_categories": categories,
        }
    except Exception as exc:
        return {
            **base,
            "status": "failed",
            "delivery_pass": False,
            "objective_quality_score": None,
            "traceable_claim_rate_v1": 0.0,
            "critical_claim_count": 0,
            "traceable_claim_count": 0,
            "failure_categories": ["runtime_or_model_failure"],
            "error": f"{type(exc).__name__}: {exc}",
        }


def annotate_critical_claims(claims: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize explicit v1 labels without inferring criticality from prose."""

    output: List[Dict[str, Any]] = []
    for index, raw in enumerate(claims, start=1):
        row = dict(raw)
        row.setdefault("claim_id", f"cl_{index:04d}")
        row["section_name"] = str(
            row.get("section_name")
            or row.get("section")
            or row.get("critical_claim_type")
            or "financial_analysis"
        )
        row["claim_text"] = str(row.get("claim_text") or row.get("text") or row.get("claim") or row.get("statement") or "")
        if not row["claim_text"].strip():
            continue
        evidence_ids = row.get("evidence_ids", row.get("citations", []))
        row["evidence_ids"] = [evidence_ids] if isinstance(evidence_ids, str) else list(evidence_ids or [])
        row["numeric_values"] = dict(row.get("numeric_values") or {}) if isinstance(row.get("numeric_values"), dict) else {}
        row.setdefault("risk_level", "medium")
        row.setdefault("confidence", 0.5)
        row.setdefault("notes", "normalized one-shot formal claim")
        declared = str(row.get("critical_claim_type") or "") if row.get("is_critical") is True else ""
        row["is_critical"] = declared in CRITICAL_CLAIM_TYPES
        row["critical_claim_type"] = declared if declared in CRITICAL_CLAIM_TYPES else ""
        output.append(ClaimItem.from_dict(row).to_dict())
    return output


def build_numeric_audit(claims: List[Dict[str, Any]], evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a reproducible linked-evidence numeric audit for formal scoring."""

    by_id = {str(row.get("evidence_id") or ""): row for row in evidence if str(row.get("evidence_id") or "")}
    rows = []
    for claim in claims:
        numeric = claim.get("numeric_values", {}) if isinstance(claim.get("numeric_values"), dict) else {}
        if not numeric:
            continue
        linked = [by_id[value] for value in claim.get("evidence_ids", []) if value in by_id]
        source_numbers = _numbers(
            " ".join(
                str(row.get("content") or "") + " " + json.dumps(row.get("metadata", {}), ensure_ascii=False)
                for row in linked
            )
        )
        supported = all(_number_is_supported(float(value), source_numbers) for value in numeric.values())
        rows.append({"claim_id": str(claim.get("claim_id") or ""), "supported": supported})
    return {"schema_version": "formal_numeric_audit.v1", "claims": rows}


def _generate_one_shot(model: Any, case: Dict[str, Any], period: str, evidence: List[Dict[str, Any]], variant: str) -> tuple[List[Dict[str, Any]], str, Dict[str, Any]]:
    prompt_evidence = _compact_prompt_evidence(evidence)
    payload = model.generate_json(
        prompt=(
            f"Variant={variant}. Company={case['company_name']} ({case['canonical_symbol']}). Period={period}. "
            "Produce sections for executive summary, three statements or explicit gaps, valuation or unavailable reason, "
            "risks, and investment conclusion. Keep the JSON and Markdown compact; do not reproduce source passages. "
            "Frozen evidence follows:\n"
            + json.dumps(prompt_evidence, ensure_ascii=False)
        ),
        system_prompt=ONE_SHOT_SYSTEM_PROMPT,
    )
    claims = payload.get("claims", [])
    markdown = str(payload.get("markdown") or "")
    if not isinstance(claims, list) or not claims or not markdown.strip():
        raise ValueError("one-shot variant did not return non-empty claims and markdown")
    return [dict(row) for row in claims if isinstance(row, dict)], markdown, {}


def _compact_prompt_evidence(evidence: List[Dict[str, Any]], content_limit: int = 12000) -> List[Dict[str, Any]]:
    """Keep one-shot prompts citation-ready without dumping raw provider payloads."""

    keys = ("evidence_id", "source_type", "title", "source_url", "publish_time", "symbol", "period", "trust_level")
    return [
        {
            **{key: row.get(key, "") for key in keys},
            "content": str(row.get("content") or "")[:content_limit],
        }
        for row in evidence
        if isinstance(row, dict)
    ]


def _generate_multi_agent(
    model: Any,
    case: Dict[str, Any],
    period: str,
    evidence: List[Dict[str, Any]],
    run_dir: Path,
    outputs: Path,
    reports: Path,
    orchestrator_factory: Callable[..., Any] = MultiAgentOrchestrator,
) -> tuple[List[Dict[str, Any]], str, Dict[str, Any]]:
    """Run the current multi-agent workflow through a snapshot-only search engine."""

    raw_data_root = run_dir / "_isolated_raw_data"
    raw_data_root.mkdir(parents=True, exist_ok=True)
    orchestrator = orchestrator_factory(
        output_dir=str(outputs),
        report_dir=str(reports),
        raw_data_root=str(raw_data_root),
        model=model,
        search_manager=_snapshot_search_manager(evidence),
        memory_enabled=False,
    )
    orchestrator.run(
        research_topic=f"{case['company_name']} ({case['canonical_symbol']}) formal FY2024 frozen-input report",
        symbol=str(case["canonical_symbol"]),
        period=period,
        requirements=[
            "Use frozen snapshot evidence only.",
            "Cover executive summary, three statements or gaps, valuation or limitation, risks, and investment conclusion.",
            "Emit explicitly labeled critical claims and body citations.",
        ],
        execution_mode="diagnostic_full",
        fast=True,
        search_engines=["formal_snapshot_bm25"],
        retrieval_ranking_mode="bm25",
        enable_remote_data=False,
        claim_contract="formal_v1",
        allow_document_enrichment=False,
    )
    claims = _read_list(outputs / "claims.json")
    markdown = (reports / "report.md").read_text(encoding="utf-8") if (reports / "report.md").exists() else ""
    if not claims or not markdown.strip():
        raise ValueError("multi-agent workflow produced no claims or markdown")
    artifacts = {
        "financial_metrics": _read_dict(outputs / "financial_metrics.json"),
        "tables": _read_list(outputs / "tables.json"),
        "valuation": _read_dict(outputs / "valuation_model.json"),
        "valuation_model": _read_dict(outputs / "valuation_model.json"),
        "valuation_sensitivity": _read_dict(outputs / "valuation_sensitivity.json"),
        "charts": _read_list(outputs / "charts.json"),
        "chart_consistency": _read_dict(outputs / "chart_consistency.json"),
        "context_evidence": _read_list(outputs / "evidence.json"),
    }
    return claims, markdown, artifacts


def _snapshot_search_manager(evidence: List[Dict[str, Any]]) -> SearchManager:
    """Expose frozen evidence through one local BM25 engine and no remote routes."""

    records = [EvidenceRecord.from_dict(row) for row in evidence]
    frozen_records = {
        str(row.get("evidence_id") or row.get("sample_id") or ""): dict(row)
        for row in evidence
        if isinstance(row, dict)
    }

    def search_snapshot(query: str, topk: int = 5, **_: Any) -> Dict[str, Any]:
        hits = BM25Index(records).search(query, topk=topk)
        selected_ids = [str(hit.record.evidence_id or hit.record.sample_id) for hit in hits]
        selected = [dict(frozen_records[evidence_id]) for evidence_id in selected_ids if evidence_id in frozen_records]
        if not selected:
            selected = [dict(frozen_records[str(record.evidence_id or record.sample_id)]) for record in records[:topk]]
        return {
            "hits": selected,
            "meta": {
                "mode": "formal_snapshot_bm25",
                "offline_only": True,
                "record_count": len(records),
                "returned_hit_count": len(selected),
            },
        }

    manager = SearchManager()
    manager.register_engine("formal_snapshot_bm25", search_snapshot)
    return manager


def _retrieve_context(evidence: List[Dict[str, Any]], case: Dict[str, Any], topk: int) -> List[Dict[str, Any]]:
    records = [EvidenceRecord.from_dict(row) for row in evidence]
    query = f"{case['company_name']} {case['canonical_symbol']} FY2024 revenue profit cash flow valuation risk"
    hits = BM25Index(records).search(query, topk=topk)
    return [hit.record.to_dict() for hit in hits] or evidence[:topk]


def _fixed_summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {"delivery_pass_rate": None, "objective_quality_score": None, "traceable_claim_rate_v1": None}
    quality = [float(row["objective_quality_score"]) for row in rows if row.get("objective_quality_score") is not None]
    return {
        "delivery_pass_rate": round(sum(1 for row in rows if row.get("delivery_pass") is True) / len(rows), 4),
        "objective_quality_score": round(sum(quality) / len(quality), 2) if quality else None,
        "traceable_claim_rate_v1": round(sum(float(row.get("traceable_claim_rate_v1") or 0.0) for row in rows) / len(rows), 4),
    }


def _secondary_summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    critical_claim_count = sum(int(row.get("critical_claim_count") or 0) for row in rows)
    traceable_claim_count = sum(int(row.get("traceable_claim_count") or 0) for row in rows)
    return {
        "run_count": len(rows),
        "evaluated_run_count": sum(1 for row in rows if row.get("status") == "evaluated"),
        "runtime_or_model_failure_count": sum(1 for row in rows if row.get("status") != "evaluated"),
        "delivery_failed_run_count": sum(1 for row in rows if row.get("delivery_pass") is not True),
        "critical_claim_count": critical_claim_count,
        "traceable_claim_count": traceable_claim_count,
        "micro_traceable_claim_rate_v1": round(traceable_claim_count / critical_claim_count, 4) if critical_claim_count else 0.0,
    }


def _render_formal_report(summary: Dict[str, Any], snapshot: Dict[str, Any]) -> str:
    lines = [
        "# Formal Frozen-Snapshot Benchmark Report",
        "",
        "## Protocol",
        "",
        f"- dataset_version: `{snapshot.get('dataset_version', '')}`",
        f"- snapshot_sha256: `{snapshot.get('snapshot_sha256', '')}`",
        f"- snapshot_complete: `{snapshot.get('complete', False)}`; validated: `{snapshot.get('valid', False)}`",
        f"- evaluated_reports: `{summary.get('report_count', 0)}/{summary.get('case_count', 0) * len(VARIANT_IDS)}`",
        "- All variants use the same frozen evidence snapshot; runtime evidence fetching is prohibited.",
        f"- Core metrics: `Delivery Pass Rate`, `Objective Quality Score`, `{TRACEABLE_V1_LABEL}`.",
        "- The primary traceability score is the macro-average of fixed-case claim rates; micro claim coverage is reported as a diagnostic below.",
        "",
        "## Overall Results",
        "",
        "| Variant | Delivery Pass Rate | Objective Quality Score | Traceable Claim Rate v1 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for variant in VARIANT_IDS:
        row = summary["variants"][variant]["overall"]
        lines.append(f"| `{variant}` | {_fmt_rate(row['delivery_pass_rate'])} | {_fmt(row['objective_quality_score'])} | {_fmt_rate(row['traceable_claim_rate_v1'])} |")
    lines.extend(["", "## Market Results", "", "| Variant | Market | Delivery Pass Rate | Objective Quality Score | Traceable Claim Rate v1 |", "| --- | --- | ---: | ---: | ---: |"])
    for variant in VARIANT_IDS:
        for market in ("US", "HK", "CN-A"):
            row = summary["variants"][variant]["by_market"][market]
            lines.append(f"| `{variant}` | {market} | {_fmt_rate(row['delivery_pass_rate'])} | {_fmt(row['objective_quality_score'])} | {_fmt_rate(row['traceable_claim_rate_v1'])} |")
    lines.extend(
        [
            "",
            "## Secondary Diagnostics",
            "",
            "| Variant | Runs Evaluated | Runtime/Model Failures | Delivery Failures | Traceable / Critical Claims | Micro Traceable Claim Rate v1 |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for variant in VARIANT_IDS:
        row = summary["variants"][variant]["secondary"]
        lines.append(
            f"| `{variant}` | {row['evaluated_run_count']}/{row['run_count']} | "
            f"{row['runtime_or_model_failure_count']} | {row['delivery_failed_run_count']} | "
            f"{row['traceable_claim_count']} / {row['critical_claim_count']} | "
            f"{_fmt_rate(row['micro_traceable_claim_rate_v1'])} |"
        )
    lines.extend(
        [
            "",
            "## Failure Taxonomy",
            "",
            "| Failure Category | Direct LLM | Single-Agent RAG | Multi-Agent RAG | Total |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    categories = sorted(summary.get("failure_counts", {}))
    if categories:
        for category in categories:
            by_variant = summary["failure_counts_by_variant"]
            lines.append(
                f"| `{category}` | {by_variant['direct_llm'].get(category, 0)} | "
                f"{by_variant['single_agent_rag'].get(category, 0)} | "
                f"{by_variant['multi_agent_rag'].get(category, 0)} | "
                f"{summary['failure_counts'].get(category, 0)} |"
            )
    else:
        lines.append("| none | 0 | 0 | 0 | 0 |")
    multi_market = summary["variants"]["multi_agent_rag"]["by_market"]
    trace_markets = [market for market in ("US", "HK", "CN-A") if multi_market[market]["traceable_claim_rate_v1"] is not None]
    delivery_markets = [market for market in ("US", "HK", "CN-A") if multi_market[market]["delivery_pass_rate"] is not None]
    weakest_trace_market = min(trace_markets, key=lambda market: multi_market[market]["traceable_claim_rate_v1"]) if trace_markets else ""
    weakest_delivery_market = min(delivery_markets, key=lambda market: multi_market[market]["delivery_pass_rate"]) if delivery_markets else ""
    lines.extend(["", "## Failure Retrospective", ""])
    if weakest_trace_market:
        lines.append(
            f"- Multi-Agent RAG traceability is weakest in `{weakest_trace_market}` "
            f"({_fmt_rate(multi_market[weakest_trace_market]['traceable_claim_rate_v1'])}); "
            "the next repair priority is denser critical-claim citation and numeric-lineage coverage in that market."
        )
    if weakest_delivery_market:
        lines.append(
            f"- Multi-Agent RAG delivery is weakest in `{weakest_delivery_market}` "
            f"({_fmt_rate(multi_market[weakest_delivery_market]['delivery_pass_rate'])}); "
            "delivery blockers should be reviewed case by case before widening the benchmark."
        )
    lines.extend(
        [
            "",
            "## Interpretation Boundary",
            "",
            "- These are formal results on the frozen FY2024 dataset version above, not results from live evidence retrieval.",
            "- The results support a comparison under this fixed protocol; they do not establish production-grade coverage or investment accuracy.",
            "- Detailed rows and failure labels are retained in `formal_runs.jsonl` and `formal_failures.csv`.",
        ]
    )
    return "\n".join(lines) + "\n"


def _numbers(text: str) -> List[float]:
    return [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", text)]


def _number_is_supported(target: float, candidates: Iterable[float]) -> bool:
    return any(abs(target - value) <= max(abs(target) * 0.01, 0.05) for value in candidates)


def _html_report(markdown: str) -> str:
    return "<html><body><pre>" + escape(markdown) + "</pre></body></html>"


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_dict(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return dict(value) if isinstance(value, dict) else {}


def _read_list(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    value = json.loads(path.read_text(encoding="utf-8"))
    return [dict(row) for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    return [
        dict(value)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
        for value in [json.loads(line)]
        if isinstance(value, dict)
    ]


def _write_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""), encoding="utf-8")


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    return f"{value:.4f}" if isinstance(value, float) and value <= 1 else f"{value:.2f}" if isinstance(value, float) else str(value)


def _fmt_rate(value: Any) -> str:
    if value is None:
        return "-"
    return f"{float(value) * 100:.2f}%"
