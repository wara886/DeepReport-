"""Summarize next data-layer review outputs into JSON and Markdown."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


DEFAULT_RUNS = [
    "eval_outputs/next_data_review_600519SS_2025Q4",
    "eval_outputs/next_data_review_AMD_2025Q4",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarize A-share/US-stock data review outputs.")
    parser.add_argument("--run-dir", action="append", default=[], help="Competition run directory. Can be repeated.")
    parser.add_argument("--chat-smoke-dir", default="eval_outputs/chat_ui_smoke_next")
    parser.add_argument("--output-json", default="eval_outputs/next_data_review_summary.json")
    parser.add_argument("--output-md", default="eval_outputs/next_data_review_summary.md")
    args = parser.parse_args(argv)

    run_dirs = [Path(item) for item in (args.run_dir or DEFAULT_RUNS)]
    rows = [summarize_run(path) for path in run_dirs]
    chat = summarize_chat_smoke(Path(args.chat_smoke_dir))
    payload = {
        "runs": rows,
        "chat_ui_smoke": chat,
        "overall": {
            "competition_passed_count": sum(1 for row in rows if row.get("competition_passed")),
            "run_count": len(rows),
            "chat_ui_passed": bool(chat.get("passed", False)),
            "remaining_data_gaps": _remaining_gaps(rows, chat),
        },
    }

    output_json = Path(args.output_json)
    output_md = Path(args.output_md)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    output_md.write_text(render_markdown(payload), encoding="utf-8")
    print(json.dumps(payload["overall"], ensure_ascii=False, indent=2))
    return 0 if payload["overall"]["competition_passed_count"] == len(rows) and payload["overall"]["chat_ui_passed"] else 2


def summarize_run(path: Path) -> Dict[str, Any]:
    summary = _read_json(path / "competition_run_summary.json", {})
    outputs = path / "company" / "outputs"
    evidence = _read_json(outputs / "evidence.json", [])
    metrics = _read_json(outputs / "financial_metrics.json", {})
    pdf_manifest = _read_json(outputs / "pdf_manifest.json", [])
    rewrite = _read_json(path / "evidence_grounded_rewrite.json", {})
    search_meta = _read_json(outputs / "search_meta.json", {})
    source_counts: Dict[str, int] = {}
    primary_count = 0
    for item in evidence if isinstance(evidence, list) else []:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source_type") or "unknown")
        source_counts[source] = source_counts.get(source, 0) + 1
        if item.get("authority_level") == "primary":
            primary_count += 1

    return {
        "run_dir": str(path),
        "symbol": summary.get("symbol", ""),
        "period": summary.get("period", ""),
        "competition_passed": bool(summary.get("competition_passed", False)),
        "company_report_score": summary.get("company_report_score", 0),
        "baseline_model_status": _nested(summary, ["baseline_deepseek_meta", "model_status"], ""),
        "source_counts": source_counts,
        "primary_evidence_count": primary_count,
        "evidence_count": len(evidence) if isinstance(evidence, list) else 0,
        "metric_count": metrics.get("metric_count", 0) if isinstance(metrics, dict) else 0,
        "present_metrics": _nested(metrics, ["coverage", "present_metrics"], []),
        "pdf_cached_count": len([row for row in pdf_manifest if isinstance(row, dict) and row.get("cache_status") == "cached"]),
        "pdf_extracted_count": len([row for row in pdf_manifest if isinstance(row, dict) and row.get("extraction_status") == "extracted"]),
        "pdf_failures": [
            {
                "evidence_id": row.get("evidence_id", ""),
                "cache_status": row.get("cache_status", row.get("status", "")),
                "extraction_status": row.get("extraction_status", ""),
                "failure_reason": row.get("failure_reason") or row.get("extraction_failure_reason") or "",
            }
            for row in pdf_manifest
            if isinstance(row, dict) and (row.get("status") == "failed" or row.get("extraction_status") == "failed")
        ],
        "rewrite_verified_count": rewrite.get("verified_rewrite_count", 0) if isinstance(rewrite, dict) else 0,
        "rewrite_pending_or_unsupported": rewrite.get("pending_or_unsupported_count", 0) if isinstance(rewrite, dict) else 0,
        "engine_failures": _engine_failures(search_meta),
        "independent_source_meta": summary.get("independent_source_meta", {}),
    }


def summarize_chat_smoke(path: Path) -> Dict[str, Any]:
    # The smoke script currently prints the result. Infer durable artifacts from output dirs.
    memory_root = path / "memory"
    return {
        "run_dir": str(path),
        "passed": (memory_root / "users").exists() and (memory_root / "long_term").exists(),
        "user_memory_files": len(list((memory_root / "users").glob("*.json"))) if (memory_root / "users").exists() else 0,
        "long_term_memory_files": len(list((memory_root / "long_term").glob("*.json"))) if (memory_root / "long_term").exists() else 0,
        "report_artifacts_present": (path / "company" / "outputs" / "run_summary.json").exists(),
    }


def render_markdown(payload: Dict[str, Any]) -> str:
    lines = [
        "# Next Data Review Summary",
        "",
        "## Overall",
        "",
        f"- competition_passed_count: {payload['overall']['competition_passed_count']} / {payload['overall']['run_count']}",
        f"- chat_ui_passed: {payload['overall']['chat_ui_passed']}",
        "",
        "## Company Runs",
        "",
    ]
    for row in payload["runs"]:
        lines.extend(
            [
                f"### {row['symbol']} {row['period']}",
                "",
                f"- competition_passed: {row['competition_passed']}",
                f"- company_report_score: {row['company_report_score']}",
                f"- evidence_sources: {json.dumps(row['source_counts'], ensure_ascii=False)}",
                f"- primary_evidence: {row['primary_evidence_count']} / {row['evidence_count']}",
                f"- metric_count: {row['metric_count']}",
                f"- present_metrics: {', '.join(str(item) for item in row['present_metrics'])}",
                f"- pdf_cached/extracted: {row['pdf_cached_count']} / {row['pdf_extracted_count']}",
                f"- rewrite_verified/pending: {row['rewrite_verified_count']} / {row['rewrite_pending_or_unsupported']}",
                f"- baseline_model_status: {row['baseline_model_status']}",
                "",
            ]
        )
    lines.extend(["## Remaining Data Gaps", ""])
    for gap in payload["overall"]["remaining_data_gaps"]:
        lines.append(f"- {gap}")
    lines.append("")
    return "\n".join(lines)


def _remaining_gaps(rows: List[Dict[str, Any]], chat: Dict[str, Any]) -> List[str]:
    gaps: List[str] = []
    for row in rows:
        if row.get("pdf_cached_count") and not row.get("pdf_extracted_count"):
            gaps.append(f"{row.get('symbol')}: PDF cached but no section extraction succeeded; install pdf extra or inspect extraction failure.")
        if int(row.get("metric_count", 0) or 0) == 0:
            gaps.append(f"{row.get('symbol')}: financial_metrics is empty.")
        if row.get("engine_failures"):
            gaps.append(f"{row.get('symbol')}: some search engines failed or skipped: {row['engine_failures'][:4]}")
    if not chat.get("passed"):
        gaps.append("Chat UI smoke artifacts are incomplete.")
    return gaps


def _engine_failures(search_meta: Any) -> List[Dict[str, str]]:
    output: List[Dict[str, str]] = []
    engine_meta = search_meta.get("engine_meta", {}) if isinstance(search_meta, dict) else {}
    for engine, meta in engine_meta.items():
        if isinstance(meta, dict) and meta.get("failure_reason"):
            output.append({"engine": str(engine), "failure_reason": str(meta.get("failure_reason"))})
    return output


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _nested(payload: Any, keys: List[str], default: Any) -> Any:
    current = payload
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return default if current is None else current


if __name__ == "__main__":
    raise SystemExit(main())
