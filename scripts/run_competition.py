"""Generate local competition deliverables for company/industry/macro reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import zipfile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.base_agent import AgentStatus, AgentTask
from src.agents.industry_research_agent import IndustryResearchAgent
from src.agents.macro_research_agent import MacroResearchAgent
from src.agents.multi_agent_orchestrator import MultiAgentOrchestrator
from src.data.independent_sources import fetch_independent_evidence_bundle
from src.models import ModelAdapter
from src.report import export_markdown_to_docx


REQUIRED_DOCX = [
    "Company_Research_Report.docx",
    "Industry_Research_Report.docx",
    "Macro_Research_Report.docx",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run DeepReport++ local competition packaging smoke.")
    parser.add_argument("--config", "--config-path", dest="config_path", default="configs/model_backends.yaml")
    parser.add_argument("--output-dir", default="eval_outputs/competition_local_packaging_smoke")
    parser.add_argument("--symbol", default="AAPL")
    parser.add_argument("--period", default="2025Q4")
    parser.add_argument("--raw-data-root", default="data/raw/real_data")
    parser.add_argument("--fast", action="store_true")
    parser.add_argument("--disable-memory", action="store_true", help="Disable durable memory for the company run.")
    parser.add_argument("--skip-company-run", action="store_true", help="Package from existing data/outputs/multi_agent artifacts.")
    parser.add_argument("--realtime-data", action="store_true", help="Fetch independent SEC/macro/policy evidence for Industry/Macro reports.")
    parser.add_argument("--data-source-config", default="configs/data_sources.yaml")
    parser.add_argument("--search-engines", default="", help="Comma-separated company-run search engines. Fast mode defaults to local_real_data.")
    parser.add_argument("--retrieval-ranking-mode", default="", help="Company-run retrieval mode. Fast mode defaults to bm25.")
    parser.add_argument(
        "--baseline-deepseek-workflow",
        action="store_true",
        help="Preserve a rich DeepSeek-style baseline draft and append agent audit buckets instead of replacing the strict path.",
    )
    parser.add_argument(
        "--baseline-model-config",
        default="configs/model_backends.yaml",
        help="Model config for optional baseline DeepSeek synthesis.",
    )
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    company_outputs_dir = output_dir / "company" / "outputs"
    company_reports_dir = output_dir / "company" / "reports"

    if args.skip_company_run:
        _copy_existing_company_artifacts(company_outputs_dir, company_reports_dir)
    else:
        orchestrator = MultiAgentOrchestrator(
            output_dir=str(company_outputs_dir),
            report_dir=str(company_reports_dir),
            config_path=args.config_path,
            raw_data_root=args.raw_data_root,
            memory_root=str(output_dir / "memory"),
            memory_enabled=not args.disable_memory,
        )
        orchestrator.run(
            research_topic=f"分析 {args.symbol} {args.period} 财务表现，并生成带引用的研究报告",
            symbol=args.symbol,
            period=args.period,
            execution_mode="dynamic",
            fast=args.fast,
            search_engines=_search_engines_for_run(args.search_engines, fast=bool(args.fast), realtime_data=bool(args.realtime_data)),
            retrieval_ranking_mode=_ranking_mode_for_run(args.retrieval_ranking_mode, fast=bool(args.fast)),
            enable_remote_data=bool(args.realtime_data),
            data_source_config_path=args.data_source_config,
        )

    company_summary = _read_json(company_outputs_dir / "run_summary.json")
    verification = _read_json(company_outputs_dir / "verification_report.json")
    multimodal = _read_json(company_outputs_dir / "multimodal_consistency.json")
    evidence_records = _read_json_optional(company_outputs_dir / "evidence.json", [])
    claims = _read_json_optional(company_outputs_dir / "claims.json", [])
    analysis_artifacts = _read_json_optional(company_outputs_dir / "analysis_artifacts.json", {})
    company_md_path = company_reports_dir / "report.md"
    company_md = company_md_path.read_text(encoding="utf-8")
    independent_payload = _fetch_independent_sources(
        symbol=args.symbol,
        period=args.period,
        evidence_records=evidence_records,
        analysis_artifacts=analysis_artifacts,
        enable_remote=bool(args.realtime_data),
        config_path=args.data_source_config,
    )
    independent_records = independent_payload["records"]
    baseline_payload = {}
    if args.baseline_deepseek_workflow:
        baseline_payload = _build_baseline_deepseek_workflow(
            symbol=args.symbol,
            period=args.period,
            strict_markdown=company_md,
            evidence_records=evidence_records if isinstance(evidence_records, list) else [],
            claims=claims if isinstance(claims, list) else [],
            verification=verification,
            model_config_path=args.baseline_model_config,
        )
        company_md = str(baseline_payload.get("markdown") or company_md)
    industry_payload = _run_industry_agent(
        symbol=args.symbol,
        period=args.period,
        company_summary=company_summary,
        evidence_records=evidence_records,
        independent_evidence_records=independent_records,
        claims=claims,
        analysis_artifacts=analysis_artifacts,
        independent_source_meta=independent_payload["meta"],
    )
    macro_payload = _run_macro_agent(
        symbol=args.symbol,
        period=args.period,
        company_summary=company_summary,
        evidence_records=evidence_records,
        independent_evidence_records=independent_records,
        claims=claims,
        independent_source_meta=independent_payload["meta"],
    )

    deliverables = output_dir / "deliverables"
    deliverables.mkdir(parents=True, exist_ok=True)
    company_docx = export_markdown_to_docx(
        company_md,
        deliverables / REQUIRED_DOCX[0],
        title=f"{args.symbol} 公司研究报告",
        metadata={"symbol": args.symbol, "period": args.period, "type": "company"},
    )
    industry_md = str(industry_payload["markdown"])
    macro_md = str(macro_payload["markdown"])
    industry_docx = export_markdown_to_docx(
        industry_md,
        deliverables / REQUIRED_DOCX[1],
        title="行业研究报告",
        metadata={"reference_symbol": args.symbol, "period": args.period, "type": "industry"},
    )
    macro_docx = export_markdown_to_docx(
        macro_md,
        deliverables / REQUIRED_DOCX[2],
        title="宏观研究报告",
        metadata={"period": args.period, "type": "macro"},
    )
    (output_dir / "industry_report.md").write_text(industry_md, encoding="utf-8")
    (output_dir / "macro_report.md").write_text(macro_md, encoding="utf-8")
    (output_dir / "industry_report.json").write_text(
        json.dumps(industry_payload.get("report_json", {}), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "macro_report.json").write_text(
        json.dumps(macro_payload.get("report_json", {}), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if baseline_payload:
        (output_dir / "baseline_deepseek_report.md").write_text(str(baseline_payload.get("markdown", "")), encoding="utf-8")
        (output_dir / "baseline_deepseek_report.json").write_text(
            json.dumps(baseline_payload.get("report_json", {}), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    zip_path = output_dir / "results.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for docx_path in [company_docx, industry_docx, macro_docx]:
            zf.write(docx_path, arcname=docx_path.name)

    package_summary = {
        "symbol": args.symbol,
        "period": args.period,
        "model": company_summary.get("model", ""),
        "company_verification_passed": bool(company_summary.get("verification_passed", False)),
        "company_verifier_passed": bool(verification.get("passed", False)),
        "multimodal_consistency_passed": bool(multimodal.get("passed", False)),
        "company_report_score": company_summary.get("company_report_overall_score", 0),
        "docx_files": _docx_status(deliverables),
        "results_zip": str(zip_path),
        "results_zip_entries": _zip_entries(zip_path),
        "competition_passed": _competition_passed(company_summary, verification, multimodal, deliverables, zip_path),
        "industry_report_generated_by": industry_payload.get("agent_name", "IndustryResearchAgent"),
        "macro_report_generated_by": macro_payload.get("agent_name", "MacroResearchAgent"),
        "industry_report_json": str(output_dir / "industry_report.json"),
        "macro_report_json": str(output_dir / "macro_report.json"),
        "baseline_deepseek_workflow_enabled": bool(args.baseline_deepseek_workflow),
        "baseline_deepseek_report_json": str(output_dir / "baseline_deepseek_report.json") if baseline_payload else "",
        "baseline_deepseek_meta": baseline_payload.get("meta", {}) if baseline_payload else {},
        "independent_source_record_count": len(independent_records),
        "independent_source_meta": independent_payload["meta"],
        "limitations": [
            _limitation_text(len(independent_records), bool(args.realtime_data))
        ],
    }
    (output_dir / "competition_run_summary.json").write_text(
        json.dumps(package_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(package_summary, ensure_ascii=False, indent=2))
    return 0 if package_summary["competition_passed"] else 2


def _copy_existing_company_artifacts(outputs_dir: Path, reports_dir: Path) -> None:
    outputs_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    source_outputs = Path("data/outputs/multi_agent")
    source_reports = Path("data/reports/multi_agent")
    required = [
        source_outputs / "run_summary.json",
        source_outputs / "verification_report.json",
        source_outputs / "multimodal_consistency.json",
        source_reports / "report.md",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("missing existing company artifacts: " + ", ".join(missing))
    for path in source_outputs.glob("*"):
        if path.is_file():
            shutil.copy2(path, outputs_dir / path.name)
    for path in source_reports.glob("*"):
        if path.is_file():
            shutil.copy2(path, reports_dir / path.name)

def _run_industry_agent(
    symbol: str,
    period: str,
    company_summary: dict,
    evidence_records: object,
    independent_evidence_records: object,
    claims: object,
    analysis_artifacts: object,
    independent_source_meta: object,
) -> dict:
    result = IndustryResearchAgent().execute_task(
        AgentTask(
            task_id="competition_industry_report",
            task_type="industry_research",
            description="Generate industry research deliverable.",
            parameters={
                "symbol": symbol,
                "period": period,
                "company_summary": company_summary,
                "evidence_records": evidence_records,
                "independent_evidence_records": independent_evidence_records,
                "claims": claims,
                "analysis_artifacts": analysis_artifacts,
                "independent_source_meta": independent_source_meta,
            },
            priority=4,
        )
    )
    if result.status != AgentStatus.COMPLETED:
        raise RuntimeError(f"IndustryResearchAgent failed: {result.error}")
    return {"agent_name": result.agent_name, **result.output}


def _run_macro_agent(
    symbol: str,
    period: str,
    company_summary: dict,
    evidence_records: object,
    independent_evidence_records: object,
    claims: object,
    independent_source_meta: object,
) -> dict:
    result = MacroResearchAgent().execute_task(
        AgentTask(
            task_id="competition_macro_report",
            task_type="macro_research",
            description="Generate macro research deliverable.",
            parameters={
                "symbol": symbol,
                "period": period,
                "company_summary": company_summary,
                "evidence_records": evidence_records,
                "independent_evidence_records": independent_evidence_records,
                "claims": claims,
                "independent_source_meta": independent_source_meta,
            },
            priority=4,
        )
    )
    if result.status != AgentStatus.COMPLETED:
        raise RuntimeError(f"MacroResearchAgent failed: {result.error}")
    return {"agent_name": result.agent_name, **result.output}


def _fetch_independent_sources(
    symbol: str,
    period: str,
    evidence_records: object,
    analysis_artifacts: object,
    enable_remote: bool,
    config_path: str,
) -> dict:
    profile = _profile_from_records(evidence_records if isinstance(evidence_records, list) else [])
    peer_context = {}
    if isinstance(analysis_artifacts, dict) and isinstance(analysis_artifacts.get("peer_context"), dict):
        peer_context = dict(analysis_artifacts["peer_context"])
    payload = fetch_independent_evidence_bundle(
        symbol=symbol,
        period=period,
        sector=str(profile.get("sector") or peer_context.get("sector") or ""),
        industry=str(profile.get("industry") or peer_context.get("industry") or ""),
        config_path=config_path,
        enable_remote=enable_remote,
    )
    return {"records": payload.get("records", []), "meta": payload.get("meta", {})}


def _build_baseline_deepseek_workflow(
    symbol: str,
    period: str,
    strict_markdown: str,
    evidence_records: list[dict],
    claims: list[dict],
    verification: dict,
    model_config_path: str,
) -> dict:
    audit = _claim_audit_buckets(claims=claims, evidence_records=evidence_records)
    fallback_markdown = _render_baseline_audit_markdown(
        symbol=symbol,
        period=period,
        strict_markdown=strict_markdown,
        audit=audit,
    )
    meta = {
        "mode": "baseline_deepseek_workflow",
        "model_used": False,
        "model_status": "not_attempted",
        "verified_claim_count": len(audit["verified"]),
        "pending_claim_count": len(audit["pending_verification"]),
        "unsupported_claim_count": len(audit["unsupported"]),
    }
    markdown = fallback_markdown
    try:
        adapter = ModelAdapter.from_config(config_path=model_config_path)
        prompt = _baseline_deepseek_prompt(
            symbol=symbol,
            period=period,
            strict_markdown=strict_markdown,
            audit=audit,
            evidence_records=evidence_records,
            verification=verification,
        )
        response = adapter.generate(
            prompt=prompt,
            system_prompt=(
                "你是 baseline_deepseek_workflow 写作后端。生成一份内容较丰富但带证据审计分层的中文研报。"
                "不要补造数字或来源；没有证据的内容必须放入待补证或不支持。"
            ),
        )
        if response.success and response.content.strip():
            markdown = _ensure_baseline_audit_section(response.content.strip(), audit=audit)
            meta["model_used"] = True
            meta["model_status"] = "completed"
            meta["model"] = response.model
        else:
            meta["model_status"] = "missing_api_key" if "missing API key" in response.error else "error"
            meta["model_error"] = response.error
    except Exception as exc:
        meta["model_status"] = "error"
        meta["model_error"] = str(exc)
    return {
        "markdown": markdown,
        "report_json": {
            "title": f"{symbol} baseline DeepSeek workflow report",
            "symbol": symbol,
            "period": period,
            "audit": audit,
            "meta": meta,
        },
        "meta": meta,
    }


def _claim_audit_buckets(claims: list[dict], evidence_records: list[dict]) -> dict:
    evidence_ids = {
        str(item.get("evidence_id") or item.get("sample_id") or "")
        for item in evidence_records
        if isinstance(item, dict) and str(item.get("evidence_id") or item.get("sample_id") or "").strip()
    }
    buckets = {"verified": [], "pending_verification": [], "unsupported": []}
    for index, claim in enumerate(claims, start=1):
        if not isinstance(claim, dict):
            continue
        claim_text = str(claim.get("claim_text") or claim.get("text") or "").strip()
        claim_id = str(claim.get("claim_id") or f"claim_{index:03d}")
        ids = claim.get("evidence_ids", [])
        ids = [str(item) for item in ids] if isinstance(ids, list) else []
        row = {"claim_id": claim_id, "claim_text": claim_text, "evidence_ids": ids}
        if ids and all(evidence_id in evidence_ids for evidence_id in ids):
            buckets["verified"].append(row)
        elif ids:
            row["missing_evidence_ids"] = [evidence_id for evidence_id in ids if evidence_id not in evidence_ids]
            buckets["unsupported"].append(row)
        else:
            buckets["pending_verification"].append(row)
    return buckets


def _render_baseline_audit_markdown(symbol: str, period: str, strict_markdown: str, audit: dict) -> str:
    lines = [
        f"# {symbol} baseline DeepSeek workflow 报告",
        "",
        "## 说明",
        "",
        f"- 本 baseline 模式用于保留 rich draft 写作风格，同时接受当前多智能体证据审计；期间：{period}。",
        "- 已证实内容可进入正文主结论；待补证内容保留为研究线索；不支持内容不得作为最终投资结论。",
        "",
        "## Rich Draft",
        "",
        strict_markdown.strip() or "暂无 baseline draft。",
        "",
    ]
    lines.extend(_audit_section_lines(audit))
    return "\n".join(lines).strip() + "\n"


def _ensure_baseline_audit_section(markdown: str, audit: dict) -> str:
    if "## 证据审计分层" in markdown:
        return markdown
    return markdown.rstrip() + "\n\n" + "\n".join(_audit_section_lines(audit)) + "\n"


def _audit_section_lines(audit: dict) -> list[str]:
    labels = [
        ("verified", "已证实"),
        ("pending_verification", "待补证"),
        ("unsupported", "不支持"),
    ]
    lines = ["## 证据审计分层", ""]
    for key, label in labels:
        rows = audit.get(key, [])
        lines.append(f"### {label}")
        if not rows:
            lines.append("- 暂无。")
        else:
            for row in rows[:12]:
                ids = ", ".join(row.get("evidence_ids", [])) if isinstance(row, dict) else ""
                text = str(row.get("claim_text", "")) if isinstance(row, dict) else str(row)
                suffix = f" [{ids}]" if ids else ""
                lines.append(f"- {text}{suffix}")
        lines.append("")
    return lines


def _baseline_deepseek_prompt(
    symbol: str,
    period: str,
    strict_markdown: str,
    audit: dict,
    evidence_records: list[dict],
    verification: dict,
) -> str:
    evidence_brief = [
        {
            "evidence_id": item.get("evidence_id") or item.get("sample_id"),
            "source_type": item.get("source_type"),
            "title": item.get("title"),
            "content": str(item.get("content", ""))[:500],
        }
        for item in evidence_records[:16]
        if isinstance(item, dict)
    ]
    return (
        f"Symbol: {symbol}\n"
        f"Period: {period}\n"
        f"Strict multi-agent draft:\n{strict_markdown[:9000]}\n\n"
        f"Evidence audit buckets:\n{json.dumps(audit, ensure_ascii=False)}\n\n"
        f"Evidence brief:\n{json.dumps(evidence_brief, ensure_ascii=False)}\n\n"
        f"Verifier report:\n{json.dumps(verification, ensure_ascii=False)}\n\n"
        "请输出 Markdown。保持报告可读性和丰富度，但必须明确分为已证实、待补证、不支持；"
        "所有事实性数字只允许来自 evidence brief 或 strict draft 中已有引用。"
    )


def _search_engines_for_run(value: str, fast: bool, realtime_data: bool = False) -> list[str] | None:
    if value.strip():
        return [item.strip() for item in value.split(",") if item.strip()]
    if realtime_data:
        return ["local_real_data", "sec_edgar", "yahoo_finance", "eastmoney", "independent_macro", "local_evidence"]
    if fast:
        return ["local_real_data"]
    return None


def _ranking_mode_for_run(value: str, fast: bool) -> str:
    if value.strip():
        return value.strip()
    if fast:
        return "bm25"
    return "hybrid_rerank"


def _profile_from_records(records: list) -> dict:
    for record in records:
        if not isinstance(record, dict):
            continue
        metadata = record.get("metadata", {}) if isinstance(record.get("metadata"), dict) else {}
        if record.get("source_type") == "company_profile" or metadata.get("sector") or metadata.get("industry"):
            return metadata
    return {}


def _limitation_text(independent_record_count: int, realtime_enabled: bool) -> str:
    if independent_record_count:
        return "Industry and macro reports include independent SEC/macro/policy evidence; source freshness and cutoff metadata define the factual boundary."
    if realtime_enabled:
        return "Realtime independent sources were requested, but no independent records were fetched; Industry/Macro reports fall back to company-run artifacts with explicit source-boundary metadata."
    return "Industry and macro reports are generated by dedicated local agents from company-run artifacts; run with --realtime-data to attach independent SEC/macro/policy evidence."


def _competition_passed(company_summary: dict, verification: dict, multimodal: dict, deliverables: Path, zip_path: Path) -> bool:
    docx_ok = all((deliverables / name).exists() and (deliverables / name).stat().st_size > 1024 for name in REQUIRED_DOCX)
    zip_ok = zip_path.exists() and sorted(_zip_entries(zip_path)) == sorted(REQUIRED_DOCX)
    return (
        bool(company_summary.get("verification_passed", False))
        and bool(verification.get("passed", False))
        and bool(multimodal.get("passed", False))
        and docx_ok
        and zip_ok
    )


def _docx_status(path: Path) -> list[dict]:
    rows = []
    for name in REQUIRED_DOCX:
        docx_path = path / name
        rows.append(
            {
                "filename": name,
                "exists": docx_path.exists(),
                "size_bytes": docx_path.stat().st_size if docx_path.exists() else 0,
            }
        )
    return rows


def _zip_entries(path: Path) -> list[str]:
    if not path.exists():
        return []
    with zipfile.ZipFile(path, "r") as zf:
        return sorted(zf.namelist())


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_json_optional(path: Path, default: object) -> object:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
