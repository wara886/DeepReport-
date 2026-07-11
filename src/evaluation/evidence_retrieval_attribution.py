"""Attribute report quality failures to source, retrieval, chunk, or writer layers."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


CORE_SECTIONS: dict[str, tuple[str, ...]] = {
    "executive_summary": ("执行摘要", "summary", "executive"),
    "business_overview": ("业务", "business", "主营", "profile"),
    "financial_analysis": ("财务", "三表", "financial", "cash flow", "income"),
    "valuation": ("估值", "valuation", "pe", "p/e", "dcf", "敏感性"),
    "risks": ("风险", "risk"),
    "conclusion": ("投资结论", "结论", "评级", "conclusion", "recommendation"),
    "peer_compare": ("同行", "peer", "可比"),
    "valuation_sensitivity": ("敏感性", "sensitivity", "dcf"),
}

OFFICIAL_SOURCE_GROUPS = {"sec_edgar", "hkex", "cninfo", "official_filing", "official_annual_report"}
STRUCTURED_SOURCE_HINTS = {"market_api", "financial_metric", "income_table", "balance_table", "cashflow_table", "pdf_statement_table"}


def build_evidence_retrieval_attribution(
    outputs_dir: str | Path,
    reports_dir: str | Path | None = None,
    run_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Build a deterministic root-cause artifact for retrieval-to-writing quality.

    The artifact intentionally does not change delivery status. It explains
    whether failures are most likely caused by unavailable source data,
    retrieval/chunking/similarity problems, or writing/review not using
    already available evidence.
    """

    outputs = Path(outputs_dir)
    search_meta = _read_json(outputs / "search_meta.json", {})
    evidence = _as_list(_read_json(outputs / "evidence.json", []))
    claims = _as_list(_read_json(outputs / "claims.json", []))
    section_dossiers = _as_dict(_read_json(outputs / "section_dossiers.json", {}))
    contracts_payload = _as_dict(_read_json(outputs / "report_section_contracts.json", {}))
    contracts = _as_dict(contracts_payload.get("contracts", contracts_payload))
    canonical_metrics = _as_dict(_read_json(outputs / "canonical_metrics.json", {}))
    section_verification = _as_dict(_read_json(outputs / "section_verification.json", {}))
    llm_review = _as_dict(_read_json(outputs / "llm_quality_review.json", {}))
    quality_report = _as_dict(_read_json(outputs / "quality_report.json", {}))
    report_text = _load_report_text(outputs=outputs, reports_dir=reports_dir)

    retrieval = _retrieval_summary(search_meta)
    metadata_quality = _chunk_metadata_quality(evidence, search_meta)
    review_issues = _review_issues_by_section(llm_review, quality_report)
    canonical_conflicts = _canonical_conflict_count(canonical_metrics, llm_review)

    section_results: dict[str, Any] = {}
    for section_key in CORE_SECTIONS:
        section_results[section_key] = _section_result(
            section_key=section_key,
            evidence=evidence,
            claims=claims,
            section_dossiers=section_dossiers,
            contracts=contracts,
            section_verification=section_verification,
            review_issues=review_issues,
            retrieval=retrieval,
            metadata_quality=metadata_quality,
            canonical_conflicts=canonical_conflicts,
            report_text=report_text,
        )

    cause_counts = Counter(
        cause
        for row in section_results.values()
        for cause in row.get("root_causes", [])
        if cause not in {"sufficient_evidence_no_blocker"}
    )
    overall_root_causes = [
        {"cause": cause, "section_count": count, "label": _cause_label(cause), "recommended_action": _recommended_action(cause)}
        for cause, count in cause_counts.most_common()
    ]
    if retrieval.get("retrieval_not_run"):
        overall_root_causes.insert(
            0,
            {
                "cause": "retrieval_not_run",
                "section_count": len(CORE_SECTIONS),
                "label": _cause_label("retrieval_not_run"),
                "recommended_action": _recommended_action("retrieval_not_run"),
            },
        )
    else:
        source_missing_sections = [
            row for row in section_results.values()
            if "source_data_missing" in row.get("root_causes", [])
        ]
    if not retrieval.get("retrieval_not_run") and source_missing_sections:
        overall_root_causes.insert(
            0,
            {
                "cause": "source_data_missing",
                "section_count": len(source_missing_sections),
                "label": _cause_label("source_data_missing"),
                "recommended_action": _recommended_action("source_data_missing"),
                "missing_sources": retrieval.get("required_sources_missing", []),
            },
        )

    return {
        "schema_version": "evidence_retrieval_attribution.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_dir": str(Path(run_dir) if run_dir is not None else outputs.parent),
        "status": "ready",
        "diagnostic_note": "This artifact attributes failure causes only; it does not relax delivery gates.",
        "retrieval_summary": retrieval,
        "chunk_metadata_quality": metadata_quality,
        "canonical_metric_conflict_count": canonical_conflicts,
        "overall_root_causes": _dedupe_causes(overall_root_causes),
        "section_results": section_results,
    }


def write_evidence_retrieval_attribution(
    outputs_dir: str | Path,
    reports_dir: str | Path | None = None,
    run_dir: str | Path | None = None,
    artifact: dict[str, Any] | None = None,
) -> dict[str, str]:
    outputs = Path(outputs_dir)
    outputs.mkdir(parents=True, exist_ok=True)
    payload = artifact or build_evidence_retrieval_attribution(outputs, reports_dir=reports_dir, run_dir=run_dir)
    path = outputs / "evidence_retrieval_attribution.json"
    path.write_text(json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return {"evidence_retrieval_attribution": str(path)}


def _section_result(
    *,
    section_key: str,
    evidence: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    section_dossiers: dict[str, Any],
    contracts: dict[str, Any],
    section_verification: dict[str, Any],
    review_issues: dict[str, list[dict[str, Any]]],
    retrieval: dict[str, Any],
    metadata_quality: dict[str, Any],
    canonical_conflicts: int,
    report_text: str,
) -> dict[str, Any]:
    dossier = _as_dict(section_dossiers.get(section_key))
    contract = _as_dict(contracts.get(section_key))
    section_evidence_ids = _section_evidence_ids(section_key, claims, dossier, contract)
    section_evidence = [item for item in evidence if _evidence_id(item) in section_evidence_ids]
    if not section_evidence and section_key in {"financial_analysis", "valuation", "executive_summary", "conclusion"}:
        section_evidence = _fallback_structured_evidence(evidence)
    official_count = sum(1 for item in section_evidence if _is_official_source(item))
    structured_count = sum(1 for item in section_evidence if _is_structured_source(item))
    pack_usage = _section_pack_usage(section_evidence=section_evidence, report_text=report_text)
    contract_status = str(contract.get("status") or "")
    contract_blockers = _as_list_of_str(contract.get("blocked_reasons"))
    section_verification_status = _section_verification_status(section_verification, section_key)
    issues = review_issues.get(section_key, [])

    causes: list[str] = []
    if retrieval.get("retrieval_not_run"):
        causes.append("retrieval_not_run")
    if not dossier and not contract:
        causes.append("section_pack_not_built")
    if not evidence:
        causes.append("source_data_missing")
    if retrieval.get("local_candidate_count", 0) <= 0 and not section_evidence:
        causes.append("retrieval_no_candidates")
    elif retrieval.get("local_returned_count", 0) <= 0 and retrieval.get("local_candidate_count", 0) > 0 and not section_evidence:
        causes.append("retrieval_no_hits")
    if retrieval.get("similarity_status") in {"unavailable", "low", "bm25_only"}:
        causes.append(f"similarity_{retrieval['similarity_status']}")
    if metadata_quality.get("status") == "poor" and (section_evidence or retrieval.get("chunking_enabled")):
        causes.append("chunk_metadata_missing")
    if retrieval.get("required_sources_missing") and official_count == 0 and section_key in {
        "business_overview",
        "financial_analysis",
        "valuation",
        "risks",
        "conclusion",
    }:
        causes.append("source_data_missing")
    if contract_status in {"gap", "blocked"} or contract_blockers:
        causes.append("section_pack_gap")
    if canonical_conflicts and section_key in {"executive_summary", "financial_analysis", "valuation", "conclusion"}:
        causes.append("canonical_metric_conflict")
    if issues and (section_evidence or structured_count > 0 or official_count > 0):
        if section_verification_status == "passed" and any(_looks_like_stale_depth_issue(issue) for issue in issues):
            causes.append("review_stale_or_overstrict")
        elif pack_usage["section_evidence_count"] and pack_usage["used_in_report_count"] <= 0:
            causes.append("writer_not_using_available_evidence")
        else:
            causes.append("writer_not_using_available_evidence")
    if not causes:
        causes.append("sufficient_evidence_no_blocker")

    causes = _unique(causes)
    primary = _primary_cause(causes)
    return {
        "section_key": section_key,
        "root_cause": primary,
        "root_causes": causes,
        "label": _cause_label(primary),
        "recommended_action": _recommended_action(primary),
        "source_record_count": retrieval.get("local_source_record_count", 0),
        "candidate_count": retrieval.get("local_candidate_count", 0),
        "returned_hit_count": retrieval.get("local_returned_count", 0),
        "section_evidence_count": len(section_evidence),
        "official_evidence_count": official_count,
        "structured_evidence_count": structured_count,
        "section_dossier_available": bool(dossier),
        "contract_status": contract_status or "missing",
        "contract_blockers": contract_blockers,
        "section_verification_status": section_verification_status,
        "review_issue_count": len(issues),
        "top_similarity": retrieval.get("vector_score_max"),
        "section_top_similarity": pack_usage.get("section_top_similarity"),
        "similarity_available": retrieval.get("similarity_status") != "unavailable",
        "similarity_status": retrieval.get("similarity_status"),
        "chunk_metadata_quality": metadata_quality,
        "section_evidence_pack_usage": pack_usage,
    }


def _section_pack_usage(*, section_evidence: list[dict[str, Any]], report_text: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    used_count = 0
    scores: list[float] = []
    for item in section_evidence:
        evidence_id = _evidence_id(item)
        metadata = _as_dict(item.get("metadata"))
        score = _first_float(
            item.get("vector_score"),
            item.get("rerank_score"),
            item.get("final_score"),
            item.get("score"),
            metadata.get("vector_score"),
            metadata.get("rerank_score"),
            metadata.get("final_score"),
        )
        if score is not None:
            scores.append(score)
        used = bool(evidence_id and evidence_id in report_text)
        if used:
            used_count += 1
        rows.append(
            {
                "evidence_id": evidence_id,
                "source_type": str(item.get("source_type") or ""),
                "title": str(item.get("title") or "")[:160],
                "vector_score": score,
                "used_in_report": used,
            }
        )
    return {
        "section_evidence_count": len(section_evidence),
        "used_in_report_count": used_count,
        "used_in_report_rate": round(used_count / len(section_evidence), 4) if section_evidence else 0.0,
        "section_top_similarity": max(scores) if scores else None,
        "section_mean_similarity": round(sum(scores) / len(scores), 6) if scores else None,
        "evidence": rows[:12],
    }


def _retrieval_summary(search_meta: Any) -> dict[str, Any]:
    meta = _as_dict(search_meta)
    engine_meta = _as_dict(meta.get("engine_meta", meta))
    local = _as_dict(engine_meta.get("local_evidence"))
    coverage = _as_dict(local.get("coverage"))
    vector_score_max = _safe_float(local.get("vector_score_max"))
    vector_score_mean = _safe_float(local.get("vector_score_mean"))
    local_source_record_count = _safe_int(local.get("source_record_count", local.get("record_count", 0)))
    local_candidate_count = _safe_int(local.get("candidate_count", local_source_record_count))
    local_returned_count = _safe_int(local.get("returned_hit_count", local.get("record_count", 0)))
    vector_hit_count = _safe_int(local.get("vector_hit_count", _as_dict(local.get("dense")).get("hit_count", 0)))
    similarity_status = "unavailable"
    if vector_score_max is not None:
        similarity_status = "low" if vector_score_max < 0.10 and local_candidate_count > 0 else "ok"
    elif local_returned_count > 0 and local_candidate_count > 0:
        similarity_status = "bm25_only"
    elif local_candidate_count <= 0:
        similarity_status = "unavailable"
    elif vector_hit_count <= 0:
        similarity_status = "unavailable"
    return {
        "retrieval_not_run": not bool(meta),
        "engines": list(meta.get("engines", [])) if isinstance(meta.get("engines"), list) else sorted(engine_meta.keys()),
        "local_mode": str(local.get("mode") or ""),
        "local_mode_effective": str(local.get("mode_effective") or ""),
        "local_source_record_count": local_source_record_count,
        "local_candidate_count": local_candidate_count,
        "local_returned_count": local_returned_count,
        "chunking_enabled": bool(local.get("chunking_enabled", False)),
        "chunk_count": _safe_int(local.get("chunk_count", 0)),
        "vector_backend": str(local.get("vector_backend") or _as_dict(local.get("dense")).get("backend") or ""),
        "vector_hit_count": vector_hit_count,
        "vector_score_min": _safe_float(local.get("vector_score_min")),
        "vector_score_max": vector_score_max,
        "vector_score_mean": vector_score_mean,
        "final_score_mean": _safe_float(local.get("final_score_mean")),
        "similarity_status": similarity_status,
        "required_sources_missing": list(coverage.get("missing_sources", [])) if isinstance(coverage.get("missing_sources"), list) else [],
        "coverage_summary": str(coverage.get("summary") or ""),
        "engine_failures": {
            key: str(value.get("failure_reason") or "")
            for key, value in engine_meta.items()
            if isinstance(value, dict) and str(value.get("failure_reason") or "")
        },
    }


def _chunk_metadata_quality(evidence: list[dict[str, Any]], search_meta: Any) -> dict[str, Any]:
    chunking_enabled = bool(_as_dict(_as_dict(search_meta).get("engine_meta", {})).get("local_evidence", {}).get("chunking_enabled", False))
    chunk_like = [
        item for item in evidence
        if item.get("chunk_id") or _as_dict(item.get("metadata")).get("section_type") or str(item.get("source_type", "")).startswith("pdf")
    ]
    rows = chunk_like or evidence
    total = len(rows)
    if total == 0:
        return {
            "status": "missing",
            "record_count": 0,
            "chunking_enabled": chunking_enabled,
            "chunk_id_present_rate": 0.0,
            "section_type_present_rate": 0.0,
            "period_present_rate": 0.0,
            "symbol_present_rate": 0.0,
        }
    rates = {
        "chunk_id_present_rate": _chunk_id_present_rate(rows),
        "section_type_present_rate": _metadata_present_rate(rows, "section_type"),
        "period_present_rate": _present_rate(rows, "period"),
        "symbol_present_rate": _present_rate(rows, "symbol"),
    }
    pdf_like_count = sum(1 for row in rows if str(row.get("source_type") or "").lower().startswith("pdf"))
    section_type_required = pdf_like_count > 0
    poor = chunking_enabled and (
        rates["chunk_id_present_rate"] < 0.50
        or (section_type_required and rates["section_type_present_rate"] < 0.30)
        or rates["period_present_rate"] < 0.80
        or rates["symbol_present_rate"] < 0.80
    )
    return {
        "status": "poor" if poor else "ok",
        "record_count": total,
        "pdf_like_count": pdf_like_count,
        "section_type_required": section_type_required,
        "chunking_enabled": chunking_enabled,
        **rates,
    }


def _section_evidence_ids(section_key: str, claims: list[dict[str, Any]], dossier: dict[str, Any], contract: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for key in ("supporting_evidence_ids", "citation_evidence_ids"):
        raw = dossier.get(key)
        if isinstance(raw, list):
            ids.update(str(item) for item in raw if str(item))
    raw = contract.get("citation_evidence_ids")
    if isinstance(raw, list):
        ids.update(str(item) for item in raw if str(item))
    for fact in contract.get("facts") or []:
        if isinstance(fact, dict) and isinstance(fact.get("evidence_ids"), list):
            ids.update(str(item) for item in fact["evidence_ids"] if str(item))
    aliases = set(CORE_SECTIONS.get(section_key, ())) | {section_key}
    for claim in claims:
        section_name = str(claim.get("section_name") or claim.get("section") or "").lower()
        claim_text = str(claim.get("claim_text") or "").lower()
        if section_key in section_name or any(str(alias).lower() in section_name or str(alias).lower() in claim_text for alias in aliases):
            raw = claim.get("evidence_ids")
            if isinstance(raw, list):
                ids.update(str(item) for item in raw if str(item))
    return ids


def _fallback_structured_evidence(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in evidence if _is_structured_source(item) or _is_official_source(item)]


def _review_issues_by_section(llm_review: dict[str, Any], quality_report: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = {key: [] for key in CORE_SECTIONS}
    for issue in _as_list(llm_review.get("issues")) + _as_list(quality_report.get("issues")):
        text = " ".join(str(issue.get(key) or "") for key in ("section", "category", "message", "detail", "description")).lower()
        for section_key, aliases in CORE_SECTIONS.items():
            if section_key in text or any(str(alias).lower() in text for alias in aliases):
                output[section_key].append(issue)
    return output


def _section_verification_status(section_verification: dict[str, Any], section_key: str) -> str:
    rows = _as_dict(section_verification.get("section_results"))
    row = _as_dict(rows.get(section_key))
    return str(row.get("status") or "missing")


def _canonical_conflict_count(canonical_metrics: dict[str, Any], llm_review: dict[str, Any]) -> int:
    if "unresolved_conflict_count" in canonical_metrics:
        count = _safe_int(canonical_metrics.get("unresolved_conflict_count", 0))
    else:
        count = _safe_int(canonical_metrics.get("conflict_count", 0))
    numeric_issue_count = sum(
        1
        for issue in _as_list(llm_review.get("issues"))
        if any(token in str(issue.get("message") or "").lower() for token in ("数值", "numeric", "mismatch", "period", "currency", "单位"))
    )
    return count + numeric_issue_count


def _primary_cause(causes: list[str]) -> str:
    priority = [
        "retrieval_not_run",
        "source_data_missing",
        "retrieval_no_candidates",
        "retrieval_no_hits",
        "similarity_low",
        "similarity_bm25_only",
        "similarity_unavailable",
        "chunk_metadata_missing",
        "section_pack_not_built",
        "section_pack_gap",
        "canonical_metric_conflict",
        "writer_not_using_available_evidence",
        "review_stale_or_overstrict",
        "sufficient_evidence_no_blocker",
    ]
    for cause in priority:
        if cause in causes:
            return cause
    return causes[0] if causes else "unknown"


def _cause_label(cause: str) -> str:
    return {
        "retrieval_not_run": "检索未执行",
        "source_data_missing": "源数据/官方证据不足",
        "retrieval_no_candidates": "向量/本地证据库没有候选材料",
        "retrieval_no_hits": "有候选材料但检索未命中",
        "similarity_low": "向量相似度偏低",
        "similarity_bm25_only": "仅记录关键词召回分数",
        "similarity_unavailable": "未记录向量相似度",
        "chunk_metadata_missing": "chunk 元数据不足",
        "section_pack_not_built": "章节证据包未构建",
        "section_pack_gap": "章节证据包存在缺口",
        "canonical_metric_conflict": "统一指标口径冲突",
        "writer_not_using_available_evidence": "写作/返工未充分使用可用证据",
        "review_stale_or_overstrict": "评审结果与运行时产物可能不一致",
        "sufficient_evidence_no_blocker": "证据链未发现阻塞",
    }.get(cause, cause)


def _recommended_action(cause: str) -> str:
    return {
        "retrieval_not_run": "检查 LangGraph collect_evidence / retrieve 节点是否执行并写入 search_meta.json。",
        "source_data_missing": "优先补采 SEC/HKEX/CNINFO/年报/公告原文，并重新解析入库。",
        "retrieval_no_candidates": "检查 PDF/表格是否已切分并写入本地证据库或向量库，确认 symbol/period 过滤条件。",
        "retrieval_no_hits": "检查查询扩展、metadata filter、section_type 和 period 过滤是否过窄。",
        "similarity_low": "检查 embedding 模型、query 改写、chunk 粒度和元标签；不要用 RRF 分数替代 cosine/vector 相似度。",
        "similarity_bm25_only": "当前已有本地候选和关键词召回结果；下一步应启用按任务隔离的向量索引并记录 vector_score，而不是继续补数据源。",
        "similarity_unavailable": "补充 vector_score_max/vector_score_mean 记录，确认当前是否退化到 BM25 或纯规则召回。",
        "chunk_metadata_missing": "补齐 chunk_id、section_type、symbol、period、page/table_id 等元数据后重建索引。",
        "section_pack_not_built": "检查 build_section_packs / contract_builder 节点，确保每个核心章节都有 evidence pack。",
        "section_pack_gap": "修复章节 evidence pack 的 allowed source、blocked reason 和 fallback 规则。",
        "canonical_metric_conflict": "先统一 canonical metric 的来源、期间、币种和单位，再让正文/估值/审稿共用同一口径。",
        "writer_not_using_available_evidence": "进入章节级改写：把 contract、section evidence pack、canonical metrics 和失败原因一起喂给 repair 节点。",
        "review_stale_or_overstrict": "复核 LLM review 输入是否读取最新 section_verification / repair / canonical_metrics。",
        "sufficient_evidence_no_blocker": "本节优先级较低，继续看其他阻塞章节。",
    }.get(cause, "检查对应 LangGraph 节点输入输出。")


def _is_official_source(item: dict[str, Any]) -> bool:
    source = _source_group(str(item.get("source_type") or ""))
    metadata = _as_dict(item.get("metadata"))
    authority = str(item.get("source_authority") or metadata.get("source_authority") or "").lower()
    level = str(item.get("authority_level") or metadata.get("authority_level") or "").lower()
    trust = str(item.get("trust_level") or metadata.get("trust_level") or "").lower()
    return source in OFFICIAL_SOURCE_GROUPS or authority == "official" or level == "primary" or trust == "official"


def _is_structured_source(item: dict[str, Any]) -> bool:
    source = _source_group(str(item.get("source_type") or ""))
    return source in STRUCTURED_SOURCE_HINTS or bool(_as_dict(item.get("metadata")).get("financials"))


def _source_group(source: str) -> str:
    normalized = str(source or "").strip().lower()
    if normalized in {"sec", "sec_edgar", "sec_10k", "sec_10q", "sec_filing", "official_10k", "official_10q"}:
        return "sec_edgar"
    if normalized in {"hkex", "hkex_announcement", "hkex_announcements", "hkex_annual_report"}:
        return "hkex"
    if normalized in {"cninfo", "cninfo_announcement", "cninfo_announcements", "exchange_announcement"}:
        return "cninfo"
    if normalized in {"annual_report_pdf_chunk", "annual_report_pdf_section_summary", "official_filing"}:
        return "official_filing"
    return normalized


def _evidence_id(item: dict[str, Any]) -> str:
    return str(item.get("evidence_id") or item.get("sample_id") or item.get("chunk_id") or "")


def _present_rate(rows: list[dict[str, Any]], key: str) -> float:
    if not rows:
        return 0.0
    return round(sum(1 for row in rows if row.get(key) not in (None, "")) / len(rows), 4)


def _chunk_id_present_rate(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    count = 0
    for row in rows:
        if row.get("chunk_id") not in (None, "") or row.get("sample_id") not in (None, "") or row.get("evidence_id") not in (None, ""):
            count += 1
    return round(count / len(rows), 4)


def _metadata_present_rate(rows: list[dict[str, Any]], key: str) -> float:
    if not rows:
        return 0.0
    count = 0
    for row in rows:
        meta = _as_dict(row.get("metadata"))
        if row.get(key) not in (None, "") or meta.get(key) not in (None, ""):
            count += 1
    return round(count / len(rows), 4)


def _looks_like_stale_depth_issue(issue: dict[str, Any]) -> bool:
    text = str(issue.get("message") or "").lower()
    return any(token in text for token in ("内容空洞", "暂不展开", "placeholder", "too generic", "hollow"))


def _load_report_text(*, outputs: Path, reports_dir: str | Path | None) -> str:
    candidates: list[Path] = []
    if reports_dir is not None:
        reports = Path(reports_dir)
        if reports.is_dir():
            candidates.extend(sorted(reports.glob("*.md")))
            candidates.extend(sorted(reports.glob("*.html")))
        elif reports.exists():
            candidates.append(reports)
    for name in ("final_report.md", "report.md", "final_report.html", "report.html"):
        candidates.append(outputs / name)
        candidates.append(outputs.parent / "reports" / name)
    chunks: list[str] = []
    seen: set[Path] = set()
    for path in candidates:
        if path in seen or not path.exists() or not path.is_file():
            continue
        seen.add(path)
        try:
            chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
    return "\n".join(chunks)


def _first_float(*values: Any) -> float | None:
    for value in values:
        parsed = _safe_float(value)
        if parsed is not None:
            return parsed
    return None


def _dedupe_causes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for row in rows:
        cause = str(row.get("cause") or "")
        if not cause or cause in seen:
            continue
        seen.add(cause)
        output.append(row)
    return output


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            output.append(item)
    return output


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _as_list_of_str(value: Any) -> list[str]:
    return [str(item) for item in value if str(item)] if isinstance(value, list) else []


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            return None
    return value
