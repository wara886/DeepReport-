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
            search_engines=_search_engines_for_run(args.search_engines, fast=bool(args.fast)),
            retrieval_ranking_mode=_ranking_mode_for_run(args.retrieval_ranking_mode, fast=bool(args.fast)),
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


def _search_engines_for_run(value: str, fast: bool) -> list[str] | None:
    if value.strip():
        return [item.strip() for item in value.split(",") if item.strip()]
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
