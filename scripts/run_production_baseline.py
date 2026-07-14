"""Run report cases through the production API and persist a diagnostic baseline."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


TERMINAL_STATUSES = {
    "completed",
    "failed",
    "timeout",
    "quality_failed",
    "review_required",
    "cancelled",
    "archived",
}

DEFAULT_CASES = (
    ("AAPL", "Apple Inc."),
    ("NVDA", "NVIDIA Corporation"),
    ("MSFT", "Microsoft Corporation"),
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an immutable production ReportTaskService/LangGraph baseline.")
    parser.add_argument("--base-url", default="http://127.0.0.1:7863")
    parser.add_argument("--period", default="FY2024")
    parser.add_argument("--symbols", nargs="*", default=[item[0] for item in DEFAULT_CASES])
    parser.add_argument("--task-prefix", default="production-baseline-v5")
    parser.add_argument("--output-root", default="data/evaluation/production_baseline_v5")
    parser.add_argument("--execution-mode", default="static", choices=("static", "dynamic", "collaborative", "diagnostic_full"))
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    parser.add_argument("--timeout-seconds", type=float, default=1200.0)
    args = parser.parse_args()

    company_names = dict(DEFAULT_CASES)
    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = Path(args.output_root) / run_stamp
    output_dir.mkdir(parents=True, exist_ok=False)

    health = request_json(args.base_url, "/api/health")
    if health.get("status") != "ok":
        raise RuntimeError(f"production service is not healthy: {health}")

    cases: list[dict[str, Any]] = []
    for raw_symbol in args.symbols:
        symbol = raw_symbol.strip().upper()
        task_id = f"{args.task_prefix}-{symbol.lower()}-{args.period.lower()}-{run_stamp.lower()}"
        payload = build_task_payload(
            task_id=task_id,
            symbol=symbol,
            company_name=company_names.get(symbol, symbol),
            period=args.period,
            execution_mode=args.execution_mode,
        )
        created = request_json(args.base_url, "/api/report-tasks", method="POST", payload=payload)
        task = wait_for_task(
            base_url=args.base_url,
            task_id=str(created["task_id"]),
            poll_seconds=args.poll_seconds,
            timeout_seconds=args.timeout_seconds,
        )
        diagnostics = request_json(args.base_url, f"/api/evaluation/report-tasks/{task_id}/diagnostics")
        cases.append(summarize_case(task, diagnostics=diagnostics))

    summary = build_summary(cases=cases, base_url=args.base_url, period=args.period, generated_at=run_stamp)
    json_path = output_dir / "baseline.json"
    markdown_path = output_dir / "baseline.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(render_markdown(summary), encoding="utf-8")
    print(json.dumps({"summary": summary["summary"], "json": str(json_path), "markdown": str(markdown_path)}, ensure_ascii=False))
    return 0


def build_task_payload(
    *,
    task_id: str,
    symbol: str,
    company_name: str,
    period: str,
    execution_mode: str = "static",
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "symbol": symbol,
        "company_name": company_name,
        "period": period,
        "research_topic": (
            f"基于官方披露、结构化财务数据和当前市场信息生成 {company_name} {period} 深度公司研究报告，"
            "明确财务期间与行情时点，覆盖业务、财务、同行、估值、风险和投资结论。"
        ),
        "report_type": "annual_review",
        "data_source_scope": "official_first",
        "execution_mode": execution_mode,
        "execution_tier": "delivery",
        "fast": False,
        "enable_remote_data": True,
        "memory_enabled": True,
        "enforce_evidence_gate": True,
        "allow_weak_evidence": False,
        "run_immediately": True,
        "run_async": True,
    }


def wait_for_task(*, base_url: str, task_id: str, poll_seconds: float, timeout_seconds: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        task = request_json(base_url, f"/api/report-tasks/{task_id}")
        if str(task.get("status") or "") in TERMINAL_STATUSES:
            return task
        time.sleep(max(poll_seconds, 0.1))
    raise TimeoutError(f"task did not reach a terminal status within {timeout_seconds}s: {task_id}")


def summarize_case(task: dict[str, Any], *, diagnostics: dict[str, Any]) -> dict[str, Any]:
    metadata = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
    output_dir = Path(str(metadata.get("output_dir") or ""))
    delivery_gate = load_json(output_dir / "delivery_gate.json")
    run_summary = load_json(output_dir / "run_summary.json")
    canonical_metrics = load_json(output_dir / "canonical_metrics.json")
    evidence = load_json(output_dir / "evidence.json")
    search_meta = load_json(output_dir / "search_meta.json")
    section_packs = load_json(output_dir / "section_evidence_packs.json")
    events = task.get("events") if isinstance(task.get("events"), list) else []
    blocker_categories = [
        str(item.get("category") or "other")
        for item in delivery_gate.get("issues", [])
        if isinstance(item, dict) and str(item.get("severity") or "") in {"fatal", "blocker"}
    ]
    evidence_rows = evidence if isinstance(evidence, list) else evidence.get("evidence", [])
    metric_rows = canonical_metrics.get("metrics", []) if isinstance(canonical_metrics, dict) else []
    packs = section_packs.get("packs", {}) if isinstance(section_packs, dict) else {}
    local_meta = search_meta.get("engine_meta", {}).get("local_evidence", {}) if isinstance(search_meta, dict) else {}
    readiness = task.get("delivery_readiness") if isinstance(task.get("delivery_readiness"), dict) else {}
    machine_quality = readiness.get("machine_quality_pass")
    if machine_quality is None:
        machine_quality = delivery_gate.get("machine_quality_pass", delivery_gate.get("delivery_pass"))
    return {
        "task_id": task.get("task_id"),
        "symbol": task.get("symbol"),
        "period": task.get("period"),
        "execution_mode": metadata.get("execution_mode"),
        "status": task.get("status"),
        "quality_score": task.get("quality_score"),
        "machine_quality": machine_quality is True,
        "formal_delivery": readiness.get("can_deliver_formal_report") is True,
        "human_review_status": str(readiness.get("human_review_status") or "unknown"),
        "workspace_id": task.get("workspace_id"),
        "company_id": task.get("company_id"),
        "duration_seconds": run_summary.get("total_duration_sec"),
        "event_stages": [f"{item.get('stage')}:{item.get('status')}" for item in events if isinstance(item, dict)],
        "executed_agents": run_summary.get("executed_agents", []),
        "evidence_count": len(evidence_rows) if isinstance(evidence_rows, list) else 0,
        "canonical_metric_count": len(metric_rows) if isinstance(metric_rows, list) else 0,
        "section_pack_count": len(packs) if isinstance(packs, (dict, list)) else 0,
        "local_retrieval": {
            "available": local_meta.get("retrieval_available"),
            "failure_reason": local_meta.get("failure_reason"),
            "mode_effective": local_meta.get("mode_effective"),
            "vector_score_max": local_meta.get("vector_score_max"),
        },
        "delivery_gate": {
            "delivery_pass": delivery_gate.get("delivery_pass"),
            "objective_score": (delivery_gate.get("scores") or {}).get("objective_total_score"),
            "llm_score": (delivery_gate.get("scores") or {}).get("llm_total_score"),
            "blocker_count": len(blocker_categories),
            "blocker_categories": sorted(set(blocker_categories)),
        },
        "diagnostic_root_causes": diagnostics.get("root_causes", []),
    }


def build_summary(*, cases: list[dict[str, Any]], base_url: str, period: str, generated_at: str) -> dict[str, Any]:
    machine_passed = sum(1 for item in cases if item.get("machine_quality") is True)
    formally_delivered = sum(1 for item in cases if item["formal_delivery"])
    quality_scores = [float(item["quality_score"]) for item in cases if isinstance(item.get("quality_score"), (int, float))]
    return {
        "schema_version": "production_baseline.v1",
        "generated_at": generated_at,
        "base_url": base_url,
        "period": period,
        "summary": {
            "case_count": len(cases),
            "machine_quality_pass_count": machine_passed,
            "machine_quality_pass_rate": round(machine_passed / len(cases), 4) if cases else None,
            "formal_delivery_count": formally_delivered,
            "formal_delivery_rate": round(formally_delivered / len(cases), 4) if cases else None,
            "average_quality_score": round(sum(quality_scores) / len(quality_scores), 4) if quality_scores else None,
            "unbound_company_count": sum(1 for item in cases if item.get("company_id") is None),
        },
        "cases": cases,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# Production Baseline",
        "",
        f"- Period: `{payload['period']}`",
        f"- Cases: `{summary['case_count']}`",
        f"- Machine quality pass rate: `{summary['machine_quality_pass_rate']}`",
        f"- Formal delivery rate: `{summary['formal_delivery_rate']}`",
        f"- Average quality score: `{summary['average_quality_score']}`",
        f"- Unbound companies: `{summary['unbound_company_count']}`",
        "",
        "| Symbol | Status | Quality | Machine | Human review | Formal | Evidence | Metrics | Local retrieval | Blockers |",
        "| --- | --- | ---: | --- | --- | --- | ---: | ---: | --- | ---: |",
    ]
    for item in payload["cases"]:
        lines.append(
            "| {symbol} | {status} | {quality} | {machine} | {review} | {formal} | {evidence} | {metrics} | {retrieval} | {blockers} |".format(
                symbol=item["symbol"],
                status=item["status"],
                quality=item["quality_score"],
                machine="yes" if item.get("machine_quality") else "no",
                review=item.get("human_review_status") or "unknown",
                formal="yes" if item["formal_delivery"] else "no",
                evidence=item["evidence_count"],
                metrics=item["canonical_metric_count"],
                retrieval=item["local_retrieval"].get("failure_reason") or "ok",
                blockers=item["delivery_gate"]["blocker_count"],
            )
        )
    lines.append("")
    return "\n".join(lines)


def request_json(base_url: str, path: str, *, method: str = "GET", payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            parsed = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError) as exc:
        raise RuntimeError(f"API request failed: {method} {path}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"API returned a non-object payload: {method} {path}")
    return parsed


def load_json(path: Path) -> dict[str, Any] | list[Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, (dict, list)) else {}


if __name__ == "__main__":
    sys.exit(main())
