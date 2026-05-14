"""Run natural-language request understanding E2E acceptance cases."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import time
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.multi_agent_orchestrator import MultiAgentOrchestrator


CASES = [
    {
        "case_id": "ru_e2e_nvda_latest_quarter",
        "query": "分析英伟达最近一个季度的经营情况，判断当前估值是否偏贵，并给出主要风险。",
    },
    {
        "case_id": "ru_e2e_moutai_deep_report",
        "query": "帮我生成一份贵州茅台的最新深度金融研报，重点关注盈利质量、估值、行业风险和同业对比。",
    },
    {
        "case_id": "ru_e2e_meta_post_earnings",
        "query": "做一份 Meta 最新财报后的公司研究，重点分析广告业务、资本开支和估值压力。",
    },
]


def main() -> int:
    run_root = PROJECT_ROOT / "eval_outputs" / "request_understanding_e2e_acceptance"
    run_root.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, Any]] = []
    for case in CASES:
        started = time.perf_counter()
        case_root = run_root / case["case_id"]
        outputs = case_root / "outputs"
        reports = case_root / "reports"
        orchestrator = MultiAgentOrchestrator(
            output_dir=str(outputs),
            report_dir=str(reports),
            raw_data_root="data/raw/real_data",
        )
        row: Dict[str, Any] = {"case_id": case["case_id"], "query": case["query"]}
        try:
            artifacts = orchestrator.run(
                natural_language_query=case["query"],
                execution_mode="dynamic",
                fast=True,
                search_engines=["local_real_data", "local_evidence"],
                retrieval_ranking_mode="hybrid_rerank",
                attachments=[],
            )
            row["status"] = artifacts.get("status", "completed")
            row["artifacts"] = artifacts
            row["error"] = ""
        except Exception as exc:
            row["status"] = "failed"
            row["artifacts"] = {}
            row["error"] = str(exc)
        row["duration_sec"] = round(time.perf_counter() - started, 4)
        row.update(_inspect_outputs(outputs, reports, row.get("artifacts", {})))
        rows.append(row)
    (run_root / "acceptance_results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_root / "acceptance_results.jsonl").write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
    print(json.dumps({"run_root": str(run_root), "case_count": len(rows), "rows": rows}, ensure_ascii=False, indent=2))
    return 0


def _inspect_outputs(outputs: Path, reports: Path, artifacts: Dict[str, Any]) -> Dict[str, Any]:
    request_path = Path(str(artifacts.get("request_understanding") or outputs / "request_understanding.json"))
    research_request_path = Path(str(artifacts.get("research_request") or outputs / "research_request.json"))
    plan_path = Path(str(artifacts.get("task_plan") or outputs / "task_plan.json"))
    report_md = Path(str(artifacts.get("report_md") or reports / "report.md"))
    report_json = Path(str(artifacts.get("report_json") or reports / "report.json"))
    verification_path = Path(str(artifacts.get("verification_report") or outputs / "verification_report.json"))
    request_payload = _read_json(request_path)
    research_payload = _read_json(research_request_path)
    return {
        "request_understanding_path": str(request_path),
        "research_request_path": str(research_request_path),
        "task_plan_path": str(plan_path),
        "report_md_path": str(report_md),
        "report_json_path": str(report_json),
        "verification_report_path": str(verification_path),
        "request_understanding_exists": request_path.exists() and request_path.stat().st_size > 0,
        "research_request_exists": research_request_path.exists() and research_request_path.stat().st_size > 0,
        "planner_entered": plan_path.exists() and plan_path.stat().st_size > 0,
        "report_generated": report_md.exists() and report_md.stat().st_size > 0 and report_json.exists() and report_json.stat().st_size > 0,
        "verification_generated": verification_path.exists() and verification_path.stat().st_size > 0,
        "ran_without_attachments": True,
        "research_request_summary": _summarize_request(request_payload or research_payload),
    }


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _summarize_request(payload: Dict[str, Any]) -> Dict[str, Any]:
    entity = payload.get("resolved_entity", {}) if isinstance(payload.get("resolved_entity"), dict) else {}
    period = payload.get("period", {}) if isinstance(payload.get("period"), dict) else {}
    output = payload.get("output_preferences", {}) if isinstance(payload.get("output_preferences"), dict) else {}
    attachments = payload.get("attachments", {}) if isinstance(payload.get("attachments"), dict) else {}
    return {
        "company_name": entity.get("company_name", ""),
        "symbol": entity.get("symbol", ""),
        "market": entity.get("market", ""),
        "confidence": entity.get("confidence", 0.0),
        "report_type": payload.get("report_type", ""),
        "period_type": period.get("type", ""),
        "focus_areas": payload.get("focus_areas", []),
        "language": output.get("language", ""),
        "format": output.get("format", ""),
        "depth": output.get("depth", ""),
        "attachments_optional": attachments.get("optional", None),
        "clarification_needed": payload.get("clarification_needed", None),
    }


if __name__ == "__main__":
    raise SystemExit(main())
