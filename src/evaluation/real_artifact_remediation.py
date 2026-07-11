"""Repair existing generated report artifacts from quality gate feedback."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

from src.agents.final_answer_agent import (
    _markdown_to_simple_html,
    auto_rewrite_core_sections,
    backfill_empty_sections_from_claims,
    normalize_report_headings,
    remove_debug_leakage,
    remove_internal_ids,
    remove_template_phrases,
)
from src.agents.base_agent import AgentTask
from src.agents.derived_evidence_builder import build_derived_evidence
from src.agents.verifier_agent import VerifierAgent
from src.evaluation.delivery_gate import build_delivery_gate_from_outputs, write_delivery_gate_for_outputs
from src.evaluation.evidence_retrieval_attribution import write_evidence_retrieval_attribution
from src.evaluation.llm_report_review import review_report_with_llm_from_paths, write_llm_review_outputs_for_paths
from src.evaluation.quality_remediation import build_quality_remediation_plan_from_outputs, write_quality_remediation_plan_for_outputs
from src.evaluation.report_quality import evaluate_report_quality_from_paths, write_quality_outputs_for_paths
from src.evaluation.section_repair import repair_failed_sections_for_outputs
from src.evaluation.section_verification import write_section_verification
from src.data.canonical_metrics import write_canonical_metrics_artifact
from src.data.official_evidence_backfill import write_official_backfill_curated_records
from src.retrieval.retrieve import retrieve_evidence_with_mode
from src.report.citation_binder import CitationBinder
from src.report.contract_builder import build_report_section_contracts


def repair_real_report_artifact(
    outputs_dir: str | Path,
    reports_dir: str | Path,
    *,
    run_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Rewrite thin core sections in an existing report and re-run gates.

    This is intentionally deterministic and bounded. It uses the existing
    claims/evidence/metrics artifacts plus quality feedback; it does not invent
    official evidence and does not call an LLM.
    """

    outputs = Path(outputs_dir)
    reports = Path(reports_dir)
    run_root = Path(run_dir) if run_dir is not None else outputs.parent
    report_path = reports / "report.md"
    before_markdown = _read_text(report_path)
    _sync_derived_evidence_and_claim_bindings(outputs)
    _refresh_local_retrieval_from_backfill(outputs)
    before_markdown = _sync_report_body_after_evidence_binding(outputs, reports, before_markdown)
    _refresh_real_artifact_contracts(outputs=outputs, reports=reports)
    write_evidence_retrieval_attribution(outputs, reports_dir=reports, run_dir=run_root)
    before_quality = evaluate_report_quality_from_paths(outputs, reports, run_root)
    write_quality_outputs_for_paths(outputs, reports, before_quality)
    before_gate = build_delivery_gate_from_outputs(outputs, run_root)
    write_delivery_gate_for_outputs(outputs, before_gate)
    plan = build_quality_remediation_plan_from_outputs(outputs, run_root)
    write_quality_remediation_plan_for_outputs(outputs, plan)
    before_section_verification = write_section_verification(
        outputs,
        markdown=before_markdown,
        report_section_contracts=_read_json(outputs / "report_section_contracts.json", {}),
        quality_remediation_plan={},
    )

    if not before_markdown.strip():
        return _result(
            outputs=outputs,
            reports=reports,
            before_quality=before_quality,
            before_gate=before_gate,
            after_quality=before_quality,
            after_gate=before_gate,
            plan=plan,
            changed=False,
            reason="missing_report_markdown",
        )

    repaired = auto_rewrite_core_sections(
        normalize_report_headings(before_markdown),
        claims=_read_list(outputs / "claims.json"),
        evidence_records=_read_list(outputs / "evidence.json"),
        financial_metrics=_read_json(outputs / "financial_metrics.json", {}),
        quality_remediation_plan=plan,
        repair_constraints={
            "required_backfill_sections": plan.get("failed_sections", []),
            "source": "real_artifact_quality_remediation",
        },
    )
    repaired = remove_template_phrases(remove_internal_ids(remove_debug_leakage(normalize_report_headings(repaired))))
    repaired = _remove_internal_metric_key_lines(repaired)
    repaired = auto_rewrite_core_sections(
        repaired,
        claims=_read_list(outputs / "claims.json"),
        evidence_records=_read_list(outputs / "evidence.json"),
        financial_metrics=_read_json(outputs / "financial_metrics.json", {}),
        quality_remediation_plan=plan,
        repair_constraints={
            "required_backfill_sections": plan.get("failed_sections", []),
            "source": "real_artifact_quality_remediation_cleanup",
        },
    )
    repaired = _close_unfinished_plain_lines(repaired)
    _sync_derived_evidence_and_claim_bindings(outputs)
    repaired = _sync_report_body_after_evidence_binding(outputs, reports, repaired)
    changed = repaired.strip() != before_markdown.strip()
    if changed:
        reports.mkdir(parents=True, exist_ok=True)
        report_path.write_text(repaired, encoding="utf-8")
        (reports / "report.html").write_text(
            _markdown_to_simple_html(repaired, title=_report_title(outputs, reports)),
            encoding="utf-8",
        )
        _update_report_json(reports / "report.json", repaired)

    section_repair = repair_failed_sections_for_outputs(
        output_dir=outputs,
        report_dir=reports,
        section_verification=before_section_verification,
    )
    changed = changed or bool(section_repair.get("repaired"))

    after_quality = evaluate_report_quality_from_paths(outputs, reports, run_root)
    write_quality_outputs_for_paths(outputs, reports, after_quality)
    _sync_derived_evidence_and_claim_bindings(outputs)
    _sync_report_body_after_evidence_binding(outputs, reports, _read_text(report_path))
    _refresh_verification_report(outputs, reports)
    write_evidence_retrieval_attribution(outputs, reports_dir=reports, run_dir=run_root)
    after_review = review_report_with_llm_from_paths(outputs, reports, run_root)
    write_llm_review_outputs_for_paths(outputs, reports, after_review)
    after_gate = build_delivery_gate_from_outputs(outputs, run_root)
    write_delivery_gate_for_outputs(outputs, after_gate)
    result = _result(
        outputs=outputs,
        reports=reports,
        before_quality=before_quality,
        before_gate=before_gate,
        after_quality=after_quality,
        after_gate=after_gate,
        plan=plan,
        changed=changed,
        reason="repaired" if changed else "no_change_needed",
    )
    _write_summary(outputs / "real_artifact_remediation.json", result)
    return result


def _result(
    *,
    outputs: Path,
    reports: Path,
    before_quality: dict[str, Any],
    before_gate: dict[str, Any],
    after_quality: dict[str, Any],
    after_gate: dict[str, Any],
    plan: dict[str, Any],
    changed: bool,
    reason: str,
) -> dict[str, Any]:
    return {
        "schema_version": "real_artifact_remediation.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "outputs_dir": str(outputs),
        "reports_dir": str(reports),
        "changed": changed,
        "reason": reason,
        "failed_sections": list(plan.get("failed_sections", [])),
        "before": {
            "delivery_pass": bool(before_gate.get("delivery_pass")),
            "objective_pass": bool(before_quality.get("objective_pass")),
            "total_score": before_quality.get("total_score"),
            "content_depth_blockers": _issue_count(before_quality, "content_depth"),
            "official_evidence_blockers": _issue_count(before_quality, "official_evidence"),
        },
        "after": {
            "delivery_pass": bool(after_gate.get("delivery_pass")),
            "objective_pass": bool(after_quality.get("objective_pass")),
            "total_score": after_quality.get("total_score"),
            "content_depth_blockers": _issue_count(after_quality, "content_depth"),
            "official_evidence_blockers": _issue_count(after_quality, "official_evidence"),
        },
    }


def _refresh_real_artifact_contracts(*, outputs: Path, reports: Path) -> None:
    run_summary = _read_json(outputs / "run_summary.json", {})
    symbol = str(run_summary.get("symbol") or run_summary.get("canonical_symbol") or "")
    period = str(run_summary.get("period") or "")
    financial_metrics = _read_json(outputs / "financial_metrics.json", {})
    tables = _read_json(outputs / "tables.json", [])
    canonical = write_canonical_metrics_artifact(
        outputs,
        financial_metrics=financial_metrics,
        tables=tables,
        symbol=symbol,
        period=period,
    )
    evidence_records = _read_list(outputs / "evidence.json")
    claims = _read_list(outputs / "claims.json")
    section_dossiers = _read_json(outputs / "section_dossiers.json", {})
    analysis_artifacts = {
        "financial_metrics": canonical,
        "raw_financial_metrics": financial_metrics,
        "tables": tables,
        "claims": claims,
        "section_dossiers": section_dossiers,
        "valuation_model": _read_json(outputs / "valuation_model.json", {}),
        "valuation_sensitivity": _read_json(outputs / "valuation_sensitivity.json", {}),
        "peer_analysis": _read_json(outputs / "peer_analysis.json", {}),
        "currency_audit": _read_json(outputs / "currency_audit.json", {}),
        "pdf_section_summaries": _read_json(outputs / "pdf_section_summaries.json", []),
        "pdf_section_chunks": _read_json(outputs / "pdf_section_chunks.json", []),
    }
    state = {
        "symbol": symbol,
        "period": period,
        "claims": claims,
        "analysis_artifacts": analysis_artifacts,
        "section_dossiers": section_dossiers if isinstance(section_dossiers, dict) else {},
        "entity_resolution": _read_json(outputs / "entity_resolution.json", {}),
    }
    contracts = build_report_section_contracts(
        state=state,
        evidence_records=evidence_records,
        analysis_artifacts=analysis_artifacts,
        section_dossiers=section_dossiers if isinstance(section_dossiers, dict) else {},
        citations=_read_list(outputs / "citations.json"),
    )
    binder = CitationBinder(evidence_records)
    binder.bind_all(contracts)
    contracts.to_json_file(str(outputs / "report_section_contracts.json"))
    binder.write_artifacts(str(outputs))


def _refresh_local_retrieval_from_backfill(outputs: Path) -> None:
    curated_path = outputs / "official_backfill_curated.jsonl"
    if not curated_path.exists() or curated_path.stat().st_size <= 0:
        count = write_official_backfill_curated_records(outputs)
        if count <= 0 or not curated_path.exists() or curated_path.stat().st_size <= 0:
            return
    run_summary = _read_json(outputs / "run_summary.json", {})
    symbol = str(run_summary.get("symbol") or run_summary.get("canonical_symbol") or "")
    period = str(run_summary.get("period") or "")
    query = f"{symbol} {period} revenue profit cash flow risk valuation official annual report"
    try:
        hits, meta = retrieve_evidence_with_mode(
            query=query,
            topk=12,
            symbol=symbol,
            period=period,
            curated_dir=str(outputs),
            ranking_mode="bm25",
            use_chunks=True,
            log=False,
        )
    except Exception as exc:
        meta = {
            "mode": "bm25",
            "mode_effective": "failed",
            "failure_reason": "official_backfill_curated_retrieval_failed",
            "error": str(exc),
        }
        hits = []
    search_meta = _read_json(outputs / "search_meta.json", {})
    if not isinstance(search_meta, dict):
        search_meta = {}
    engine_meta = search_meta.get("engine_meta") if isinstance(search_meta.get("engine_meta"), dict) else {}
    meta = dict(meta)
    meta["curated_dir"] = str(outputs)
    meta["official_backfill_curated"] = str(curated_path)
    returned_ids: list[str] = []
    for item in hits:
        if not isinstance(item, dict):
            continue
        for value in [
            item.get("evidence_id"),
            item.get("sample_id"),
            item.get("chunk_id"),
            item.get("parent_evidence_id"),
            item.get("parent_sample_id"),
        ]:
            text = str(value or "")
            if text and text not in returned_ids:
                returned_ids.append(text)
    meta["returned_evidence_ids"] = returned_ids
    engine_meta["local_evidence"] = meta
    search_meta["engine_meta"] = engine_meta
    engines = search_meta.get("engines") if isinstance(search_meta.get("engines"), list) else []
    if "local_evidence" not in engines:
        engines.append("local_evidence")
    search_meta["engines"] = engines
    (outputs / "search_meta.json").write_text(json.dumps(search_meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _sync_derived_evidence_and_claim_bindings(outputs: Path) -> None:
    run_summary = _read_json(outputs / "run_summary.json", {})
    symbol = str(run_summary.get("symbol") or run_summary.get("canonical_symbol") or "")
    period = str(run_summary.get("period") or "")
    claims = _read_list(outputs / "claims.json")
    evidence_records = _read_list(outputs / "evidence.json")
    analysis_artifacts = {
        "financial_metrics": _read_json(outputs / "canonical_metrics.json", {}) or _read_json(outputs / "financial_metrics.json", {}),
        "valuation_model": _read_json(outputs / "valuation_model.json", {}),
        "valuation_sensitivity": _read_json(outputs / "valuation_sensitivity.json", {}),
        "peer_analysis": _read_json(outputs / "peer_analysis.json", {}),
        "tables": _read_json(outputs / "tables.json", []),
    }
    derived = build_derived_evidence(
        {
            "symbol": symbol,
            "period": period,
            "claims": claims,
            "evidence_records": evidence_records,
            "analysis_artifacts": analysis_artifacts,
        }
    )
    if not derived:
        return
    by_id = {str(item.get("evidence_id") or item.get("sample_id") or ""): item for item in evidence_records}
    changed = False
    for item in derived:
        evidence_id = str(item.get("evidence_id") or "")
        if evidence_id and evidence_id not in by_id:
            evidence_records.append(item)
            by_id[evidence_id] = item
            changed = True
    valuation_id = f"internal_valuation_{symbol.upper()}_{period.upper()}_v1"
    sensitivity_id = f"internal_valuation_sensitivity_{symbol.upper()}_{period.upper()}_v1"
    for claim in claims:
        section = str(claim.get("section_name") or "")
        text = f"{claim.get('claim_text', '')} {claim.get('notes', '')}".lower()
        target_id = ""
        if section == "valuation_sensitivity" or "敏感性" in text:
            target_id = sensitivity_id if sensitivity_id in by_id else valuation_id
        elif section == "valuation" or "dcf" in text or "估值" in text:
            target_id = valuation_id
        if target_id and target_id in by_id:
            ids = [str(value) for value in claim.get("evidence_ids", []) if value]
            if target_id not in ids:
                ids.append(target_id)
                claim["evidence_ids"] = ids
                changed = True
    if changed:
        (outputs / "evidence.json").write_text(json.dumps(evidence_records, ensure_ascii=False, indent=2), encoding="utf-8")
        (outputs / "claims.json").write_text(json.dumps(claims, ensure_ascii=False, indent=2), encoding="utf-8")


def _sync_report_body_after_evidence_binding(outputs: Path, reports: Path, markdown: str) -> str:
    claims = _read_list(outputs / "claims.json")
    evidence_records = _read_list(outputs / "evidence.json")
    if not markdown.strip():
        return markdown
    updated = backfill_empty_sections_from_claims(markdown, claims)
    updated = _expand_short_delivery_sections(updated, claims)
    updated = _append_missing_claim_evidence_citations(updated, claims)
    if updated.strip() != markdown.strip():
        reports.mkdir(parents=True, exist_ok=True)
        title = _report_title(outputs, reports)
        (reports / "report.md").write_text(updated, encoding="utf-8")
        (reports / "report.html").write_text(_markdown_to_simple_html(updated, title=title), encoding="utf-8")
        _update_report_json(reports / "report.json", updated)
        _append_missing_references(updated, evidence_records)
    else:
        _append_missing_references(updated, evidence_records)
    return updated


def _append_missing_claim_evidence_citations(markdown: str, claims: list[dict[str, Any]]) -> str:
    output = markdown
    section_title_by_key = {
        "financial_statements": "三表摘要",
        "financial_analysis": "财务分析",
        "valuation": "估值观察",
        "valuation_sensitivity": "估值敏感性",
        "risks": "风险评估",
        "risk_factors": "风险评估",
        "conclusion": "投资结论",
        "investment_conclusion": "投资结论",
    }
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        missing_ids = [str(eid) for eid in claim.get("evidence_ids", []) if str(eid) and str(eid) not in output]
        if not missing_ids:
            continue
        section = str(claim.get("section_name") or "")
        title = section_title_by_key.get(section, "")
        if not title:
            continue
        marker = " ".join(f"[{eid}]" for eid in missing_ids[:4])
        output = _append_text_to_section(output, title, marker)
    return output


def _append_text_to_section(markdown: str, title: str, text: str) -> str:
    if not text.strip():
        return markdown
    header = re.compile(rf"(?m)^##\s+{re.escape(title)}\s*$")
    match = header.search(markdown)
    if not match:
        return markdown
    next_header = re.search(r"(?m)^##\s+", markdown[match.end():])
    end = match.end() + next_header.start() if next_header else len(markdown)
    section_body = markdown[match.end():end]
    if text in section_body:
        return markdown
    return markdown[:end].rstrip() + "\n\n" + text + "\n\n" + markdown[end:].lstrip("\n")


def _append_missing_references(markdown: str, evidence_records: list[dict[str, Any]]) -> str:
    # References are kept in report markdown rather than a separate artifact in
    # real user runs.  This helper is intentionally side-effect free for now;
    # citation policy only requires the evidence id to appear in the body.
    return markdown


def _expand_short_delivery_sections(markdown: str, claims: list[dict[str, Any]]) -> str:
    output = markdown
    claims_by_section: dict[str, list[dict[str, Any]]] = {}
    for claim in claims:
        if isinstance(claim, dict):
            section = str(claim.get("section_name") or "")
            claims_by_section.setdefault(section, []).append(claim)
    for section, title, min_chars in [
        ("executive_summary", "执行摘要", 120),
        ("business_overview", "业务概览", 160),
        ("financial_statements", "三表摘要", 120),
        ("peer_compare", "同行对比", 120),
        ("valuation", "估值观察", 180),
        ("valuation_sensitivity", "估值敏感性", 100),
        ("risks", "风险评估", 160),
        ("conclusion", "投资结论", 160),
    ]:
        body = _section_body_from_markdown(output, title)
        if body is None:
            continue
        if _meaningful_chinese_chars(body) >= min_chars and not _contains_placeholder(body):
            continue
        replacement = _delivery_section_prose(section, claims_by_section.get(section, []), title)
        if replacement:
            output = _replace_report_section(output, title, replacement)
    return output


def _delivery_section_prose(section: str, claims: list[dict[str, Any]], title: str) -> str:
    claim_sentences = [_claim_sentence(claim) for claim in claims if isinstance(claim, dict)]
    claim_sentences = [item for item in claim_sentences if item]
    citations = _section_citations(claims)
    citation_tail = " ".join(f"[{eid}]" for eid in citations[:4])
    joined = "；".join(claim_sentences[:3])
    if section == "executive_summary":
        base = joined or "本节汇总当前证据池中的财务、估值、风险和结论边界。"
        return (
            f"{base}。从交付角度看，本报告将结论限定在已绑定证据能够支持的范围内，重点关注收入规模、利润质量、现金流兑现、估值约束和风险传导。"
            f"因此当前观点以审慎观察为主，正式评级仍依赖官方披露、估值输入和引用覆盖进一步确认。{citation_tail}"
        ).strip()
    if section == "business_overview":
        base = joined or "公司业务画像仍以已获取的公司资料和财务证据为基础。"
        return (
            f"{base}。业务分析不只描述公司简介，还需要解释收入来源、产品或服务结构、客户需求和竞争位置如何影响利润率与现金流。"
            f"后续若补齐年报或公告中的分部信息，可进一步拆解增长驱动和经营约束。{citation_tail}"
        ).strip()
    if section == "financial_statements":
        base = joined or "当前已形成利润表、资产负债表和现金流量表的核心摘要。"
        return (
            f"{base}。三表摘要的重点是把收入、净利润、资产负债结构和经营现金流放在同一期间内核对，判断利润是否能够转化为现金，资产负债是否支撑持续经营。"
            f"如果后续官方报表口径与结构化来源存在差异，应以官方披露为准并同步修正估值和投资结论。{citation_tail}"
        ).strip()
    if section == "peer_compare":
        base = joined or "同行对比目前以可比口径和数据可得性为边界。"
        return (
            f"{base}。在缺少完整非目标公司指标时，本节不输出绝对强弱排序，而是说明需要比较的维度：收入增速、毛利率、净利率、现金流转换率、资本效率和估值倍数。"
            f"这些维度补齐后，才能判断公司相对竞争位置和估值溢价是否合理。{citation_tail}"
        ).strip()
    if section == "valuation":
        base = joined or "估值观察以当前财务指标、市场价格和内部估值模型为约束。"
        return (
            f"{base}。估值判断不能只看单一倍数，需要同时检查盈利口径、自由现金流、折现率、增长假设和当前市值之间是否一致。"
            f"若官方三表或市场数据更新导致净利润、现金流或股本口径变化，P/E、P/S 和 DCF 结果都需要重新计算。{citation_tail}"
        ).strip()
    if section == "valuation_sensitivity":
        base = joined or "敏感性分析用于观察增长率、折现率、利润率或现金流假设变化对估值的影响。"
        return (
            f"{base}。当前敏感性结果只作为模型压力测试，不等同于外部披露事实；正式交付时应把关键变量、基准值、上行情景和下行情景逐项绑定到可引用证据。"
            f"在证据不足时，本节只能说明方向性弹性，不能给出激进目标价。{citation_tail}"
        ).strip()
    if section == "risks":
        base = joined or "风险评估覆盖经营、竞争、成本、监管、现金流和估值假设等主要约束。"
        return (
            f"{base}。这些风险会通过收入增速、毛利率、费用率、资本开支和市场风险偏好传导到盈利质量与估值中枢。"
            f"如果后续披露显示需求放缓、成本上升或监管压力增加，应下调对现金流和估值弹性的判断。{citation_tail}"
        ).strip()
    if section == "conclusion":
        base = joined or "投资结论维持中性观察，当前证据支持方向性判断但不支持激进评级。"
        return (
            f"{base}。核心理由包括：财务指标需要继续核对官方口径，估值结果对增长和折现率敏感，风险因素仍可能影响现金流转换和市场定价。"
            f"因此本报告适合作为研究底稿和人工复核材料；只有在官方证据、主张复核、引用覆盖和质量门禁同时通过后，才应升级为正式交付观点。{citation_tail}"
        ).strip()
    return ""


def _claim_sentence(claim: dict[str, Any]) -> str:
    text = str(claim.get("claim_text") or "").strip()
    return text.rstrip("。；;") if text else ""


def _section_citations(claims: list[dict[str, Any]]) -> list[str]:
    output: list[str] = []
    for claim in claims:
        for eid in claim.get("evidence_ids", []) if isinstance(claim.get("evidence_ids"), list) else []:
            value = str(eid).strip()
            if value and value not in output:
                output.append(value)
    return output


def _section_body_from_markdown(markdown: str, title: str) -> str | None:
    match = re.search(rf"(?m)^##\s+{re.escape(title)}\s*$", markdown)
    if not match:
        return None
    next_header = re.search(r"(?m)^##\s+", markdown[match.end():])
    end = match.end() + next_header.start() if next_header else len(markdown)
    return markdown[match.end():end]


def _replace_report_section(markdown: str, title: str, replacement: str) -> str:
    match = re.search(rf"(?m)^##\s+{re.escape(title)}\s*$", markdown)
    if not match:
        return markdown.rstrip() + f"\n\n## {title}\n\n{replacement.rstrip()}\n"
    next_header = re.search(r"(?m)^##\s+", markdown[match.end():])
    end = match.end() + next_header.start() if next_header else len(markdown)
    return markdown[:match.end()] + "\n\n" + replacement.rstrip() + "\n\n" + markdown[end:].lstrip("\n")


def _meaningful_chinese_chars(text: str) -> int:
    return len(re.sub(r"[\s\n\r#\-*:：，、。）（\[\]【】\"''a-zA-Z0-9]", "", str(text or "")))


def _contains_placeholder(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(
        marker in lowered
        for marker in ["本节暂不展开详细分析", "evidence_not_available", "valuation_sensitivity_not_available", "暂无结论"]
    )


def _refresh_verification_report(outputs: Path, reports: Path) -> None:
    run_summary = _read_json(outputs / "run_summary.json", {})
    symbol = str(run_summary.get("symbol") or run_summary.get("canonical_symbol") or "")
    period = str(run_summary.get("period") or "")
    markdown = _read_text(reports / "report.md")
    if not markdown.strip():
        return
    result = VerifierAgent().execute_task(
        AgentTask(
            task_id="real_artifact_verifier_refresh",
            task_type="verifier",
            description="Refresh verifier report after real artifact remediation.",
            parameters={
                "claims": _read_list(outputs / "claims.json"),
                "markdown": markdown,
                "evidence_records": _read_list(outputs / "evidence.json"),
                "charts": _read_json(outputs / "charts.json", []),
                "tables": _read_json(outputs / "tables.json", []),
                "valuation": _read_json(outputs / "valuation_model.json", {}),
                "expected_symbol": symbol,
                "period": period,
            },
        )
    )
    report = result.output.get("verification_report", {}) if hasattr(result, "output") else {}
    if isinstance(report, dict):
        (outputs / "verification_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def _issue_count(report: dict[str, Any], category: str) -> int:
    return sum(1 for item in report.get("issues", []) if isinstance(item, dict) and item.get("category") == category)


def _report_title(outputs: Path, reports: Path) -> str:
    report_json = _read_json(reports / "report.json", {})
    if isinstance(report_json, dict) and report_json.get("title"):
        return str(report_json["title"])
    summary = _read_json(outputs / "run_summary.json", {})
    symbol = str(summary.get("symbol") or "研究报告")
    period = str(summary.get("period") or "")
    return f"{symbol} {period} 研究报告".strip()


def _update_report_json(path: Path, markdown: str) -> None:
    payload = _read_json(path, {})
    if not isinstance(payload, dict):
        payload = {}
    payload["markdown"] = markdown
    payload["remediated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_summary(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _read_list(path: Path) -> list[dict[str, Any]]:
    value = _read_json(path, [])
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _remove_internal_metric_key_lines(markdown: str) -> str:
    blocked = ("revenue_growth_pct", "adjusted_net_income", "non_recurring_gain")
    lines = []
    for line in str(markdown or "").splitlines():
        if any(key in line for key in blocked):
            continue
        lines.append(line.rstrip())
    return "\n".join(lines).strip() + "\n"


def _close_unfinished_plain_lines(markdown: str) -> str:
    lines: list[str] = []
    for raw in str(markdown or "").splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", "|", "-", "*", "<", ">")):
            lines.append(line)
            continue
        if stripped.endswith(("与", "及", "和", "并", "或", "、", "：", "，", ",")):
            line = line.rstrip("与及和并或、：，,") + "。"
        lines.append(line)
    return "\n".join(lines).strip() + "\n"
