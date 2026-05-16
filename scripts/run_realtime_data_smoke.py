"""Smoke test for independent realtime evidence and DeepSeek-backed synthesis."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.base_agent import AgentTask
from src.agents.browser_agent import normalize_evidence_candidates
from src.agents.industry_research_agent import IndustryResearchAgent
from src.agents.macro_research_agent import MacroResearchAgent
from src.data.independent_sources import fetch_independent_evidence_bundle
from src.models import ModelAdapter
from src.report import export_markdown_to_docx
from src.search import SearchManager


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run DeepReport++ independent realtime data smoke.")
    parser.add_argument("--symbol", default="AAPL")
    parser.add_argument("--period", default="2025Q4")
    parser.add_argument("--output-dir", default="eval_outputs/realtime_data_smoke")
    parser.add_argument("--config-path", default="configs/model_backends.yaml")
    parser.add_argument("--data-source-config", default="configs/data_sources.yaml")
    parser.add_argument("--raw-data-root", default="data/raw/real_data")
    parser.add_argument("--enable-remote-data", action="store_true")
    parser.add_argument("--use-deepseek", action="store_true")
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    independent = fetch_independent_evidence_bundle(
        symbol=args.symbol,
        period=args.period,
        config_path=args.data_source_config,
        enable_remote=bool(args.enable_remote_data),
        topk=10,
    )
    search_payload = _run_remote_search(
        symbol=args.symbol,
        period=args.period,
        raw_data_root=args.raw_data_root,
        enable_remote=bool(args.enable_remote_data),
        data_source_config=args.data_source_config,
    )
    search_records = normalize_evidence_candidates(search_payload.get("hits", []))
    independent_records = list(independent.get("records", []))
    all_independent_records = _dedupe(independent_records + search_records)
    deepseek = _run_deepseek_probe(
        use_deepseek=bool(args.use_deepseek),
        config_path=args.config_path,
        records=all_independent_records,
    )
    industry = _run_agent(
        IndustryResearchAgent(),
        task_id="realtime_industry",
        task_type="industry_research",
        symbol=args.symbol,
        period=args.period,
        independent_records=all_independent_records,
        independent_meta=independent.get("meta", {}),
    )
    macro = _run_agent(
        MacroResearchAgent(),
        task_id="realtime_macro",
        task_type="macro_research",
        symbol=args.symbol,
        period=args.period,
        independent_records=all_independent_records,
        independent_meta=independent.get("meta", {}),
    )

    (output_dir / "independent_evidence.json").write_text(
        json.dumps(all_independent_records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "search_meta.json").write_text(json.dumps(search_payload.get("meta", {}), ensure_ascii=False, indent=2), encoding="utf-8")
    _write_report(output_dir, "industry_report", industry)
    _write_report(output_dir, "macro_report", macro)
    summary = {
        "symbol": args.symbol,
        "period": args.period,
        "remote_data_enabled": bool(args.enable_remote_data),
        "independent_record_count": len(all_independent_records),
        "independent_source_meta": independent.get("meta", {}),
        "search_meta": search_payload.get("meta", {}),
        "deepseek": deepseek,
        "industry_report_json": str(output_dir / "industry_report.json"),
        "industry_report_docx": str(output_dir / "industry_report.docx"),
        "macro_report_json": str(output_dir / "macro_report.json"),
        "macro_report_docx": str(output_dir / "macro_report.docx"),
        "passed": bool(all_independent_records) or not args.enable_remote_data,
    }
    (output_dir / "realtime_data_smoke_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _run_remote_search(
    symbol: str,
    period: str,
    raw_data_root: str,
    enable_remote: bool,
    data_source_config: str,
) -> dict:
    if not enable_remote:
        return {"hits": [], "meta": {"mode": "remote_search", "failure_reason": "remote_sources_disabled"}}
    manager = SearchManager.with_local_sources()
    return manager.search(
        query=f"{symbol} {period} industry macro official data",
        topk=8,
        engines=["sec_edgar", "independent_macro", "yahoo_finance", "tavily", "serper"],
        symbol=symbol,
        period=period,
        raw_data_root=raw_data_root,
        data_source_config_path=data_source_config,
        enable_remote=True,
    )


def _run_deepseek_probe(use_deepseek: bool, config_path: str, records: list[dict]) -> dict:
    if not use_deepseek:
        return {"enabled": False, "status": "skipped"}
    adapter = ModelAdapter.from_config(config_path=config_path)
    response = adapter.generate(
        prompt=(
            "请用三句话概括以下独立金融证据的宏观/行业含义，并明确不要补造缺失数据。\n"
            f"Evidence: {records[:5]}"
        ),
        system_prompt="你是金融多智能体系统的实时证据 smoke tester。",
    )
    if not response.success:
        status = "missing_api_key" if "missing API key" in response.error else "error"
        return {"enabled": True, "status": status, "error": response.error, "model": response.model}
    return {"enabled": True, "status": "completed", "model": response.model, "content_preview": response.content[:500]}


def _run_agent(
    agent,
    task_id: str,
    task_type: str,
    symbol: str,
    period: str,
    independent_records: list[dict],
    independent_meta: dict,
) -> dict:
    result = agent.execute_task(
        AgentTask(
            task_id=task_id,
            task_type=task_type,
            description=f"Generate {task_type} realtime smoke report.",
            parameters={
                "symbol": symbol,
                "period": period,
                "company_summary": {"verification_passed": True, "multimodal_consistency_passed": True},
                "evidence_records": [],
                "independent_evidence_records": independent_records,
                "claims": [],
                "analysis_artifacts": {},
                "independent_source_meta": independent_meta,
            },
        )
    )
    if result.error:
        raise RuntimeError(result.error)
    return {"agent_name": result.agent_name, **result.output}


def _write_report(output_dir: Path, stem: str, payload: dict) -> None:
    markdown = str(payload.get("markdown", ""))
    (output_dir / f"{stem}.md").write_text(markdown, encoding="utf-8")
    (output_dir / f"{stem}.json").write_text(
        json.dumps(payload.get("report_json", {}), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    export_markdown_to_docx(markdown, output_dir / f"{stem}.docx", title=stem.replace("_", " ").title())


def _dedupe(records: list[dict]) -> list[dict]:
    seen: set[str] = set()
    output: list[dict] = []
    for record in records:
        key = str(record.get("evidence_id") or record.get("sample_id") or record.get("source_url") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(record)
    return output


if __name__ == "__main__":
    raise SystemExit(main())
