"""Runtime source and key health check for FinSight.

The script only reports whether credentials are present and whether each
configured runtime source can return a small response. It masks secrets and
does not write generated reports.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.independent_sources import fetch_macro_evidence  # noqa: E402
from src.models.model_adapter import ModelAdapter  # noqa: E402
from src.search.search_manager import SearchManager  # noqa: E402
from src.utils.env import load_env_files  # noqa: E402


KEYS = [
    "DEEPSEEK_API_KEY",
    "TAVILY_API_KEY",
    "SERPER_API_KEY",
    "FRED_API_KEY",
    "BLS_API_KEY",
    "BEA_API_KEY",
    "SEC_USER_AGENT",
    "WRITER_REMOTE_API_KEY",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Check FinSight runtime source health.")
    parser.add_argument("--output", default="", help="Optional JSON output path.")
    parser.add_argument("--markdown-output", default="", help="Optional Markdown summary path.")
    parser.add_argument("--config", default="configs/data_sources.yaml")
    args = parser.parse_args()

    result = run_checks(config_path=args.config)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.markdown_output:
        md = Path(args.markdown_output)
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text(render_markdown(result), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def run_checks(config_path: str = "configs/data_sources.yaml") -> Dict[str, Any]:
    load_env_files(config_path=config_path)
    load_env_files(config_path="configs/model_backends.yaml")
    manager = SearchManager.with_local_sources()

    result: Dict[str, Any] = {
        "schema_version": "runtime_source_health.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "keys_present": {key: bool(os.environ.get(key, "").strip()) for key in KEYS},
        "recommended_warnings": [],
        "model": {},
        "search": {},
        "macro": {},
        "company": {},
    }
    if not result["keys_present"]["SEC_USER_AGENT"]:
        result["recommended_warnings"].append("SEC_USER_AGENT 未配置；建议使用真实项目名和联系邮箱，降低 SEC 限流风险。")
    if not result["keys_present"]["WRITER_REMOTE_API_KEY"]:
        result["recommended_warnings"].append("WRITER_REMOTE_API_KEY 未配置；当前 template_only 写作模式不需要它。")

    result["model"]["deepseek"] = _check_deepseek()
    result["search"]["tavily"] = _check_engine(manager, "tavily", "AMD 2025 annual report revenue SEC", "AMD")
    result["search"]["serper"] = _check_engine(manager, "serper", "AMD 2025 annual report revenue SEC", "AMD")

    macro = fetch_macro_evidence(period="2025Q4", config_path=config_path, topk=8).to_dict()
    result["macro"] = {
        "ok": int(macro.get("meta", {}).get("record_count") or 0) > 0,
        "record_count": macro.get("meta", {}).get("record_count", 0),
        "failure_reason": macro.get("meta", {}).get("failure_reason", ""),
        "source_meta": macro.get("meta", {}).get("source_meta", {}),
    }

    result["company"]["600519.SS"] = _check_company(
        manager,
        symbol="600519.SS",
        engines=[
            "local_real_data",
            "cninfo_announcements",
            "exchange_announcements",
            "eastmoney_financials",
            "yahoo_finance",
            "eastmoney",
            "local_evidence",
        ],
    )
    result["company"]["AMD"] = _check_company(
        manager,
        symbol="AMD",
        engines=[
            "local_real_data",
            "sec_edgar",
            "yahoo_finance",
            "independent_macro",
            "tavily",
            "serper",
            "local_evidence",
        ],
    )
    return result


def _check_deepseek() -> Dict[str, Any]:
    try:
        adapter = ModelAdapter.from_config("configs/model_backends.yaml")
        payload = adapter.generate_json('Return exactly {"ok": true}.', system_prompt="Return JSON only.")
        return {"ok": payload.get("ok") is True, "model": adapter.model_name, "status": "ok"}
    except Exception as exc:
        return {"ok": False, "status": "failed", "error": str(exc)}


def _check_engine(manager: SearchManager, engine: str, query: str, symbol: str) -> Dict[str, Any]:
    payload = manager.search(query=query, engines=[engine], topk=2, symbol=symbol, period="2025Q4", enable_remote=True)
    meta = payload.get("meta", {}).get("engine_meta", {}).get(engine, {})
    error = meta.get("error", "")
    returned = int(payload.get("meta", {}).get("returned_hits") or 0)
    return {
        "ok": returned > 0 and not error,
        "status": "ok" if returned > 0 and not error else "failed",
        "returned_hits": returned,
        "meta": meta,
    }


def _check_company(manager: SearchManager, symbol: str, engines: List[str]) -> Dict[str, Any]:
    payload = manager.search(
        query=f"{symbol} 2025Q4 annual report revenue cash flow valuation peers",
        topk=10,
        engines=engines,
        symbol=symbol,
        period="2025Q4",
        enable_remote=True,
    )
    engine_meta = payload.get("meta", {}).get("engine_meta", {})
    status = {}
    for engine, meta in engine_meta.items():
        status[engine] = {
            "record_count": meta.get("record_count", meta.get("result_count", "")),
            "returned_hit_count": meta.get("returned_hit_count", ""),
            "failure_reason": meta.get("failure_reason", ""),
            "error": meta.get("error", ""),
            "has_financials": meta.get("has_financials", ""),
            "skipped_files": meta.get("skipped_files", []),
        }
    return {
        "ok": int(payload.get("meta", {}).get("returned_hits") or 0) > 0,
        "returned_hits": payload.get("meta", {}).get("returned_hits", 0),
        "engine_status": status,
        "hit_sources": [hit.get("source_type") for hit in payload.get("hits", [])[:10]],
    }


def render_markdown(result: Dict[str, Any]) -> str:
    lines = ["# Runtime Source Health", ""]
    lines.append(f"- generated_at: `{result.get('generated_at')}`")
    lines.append("")
    lines.append("## Keys")
    for key, present in dict(result.get("keys_present", {})).items():
        lines.append(f"- {key}: {'configured' if present else 'missing'}")
    lines.append("")
    lines.append("## Warnings")
    warnings = result.get("recommended_warnings", []) or []
    lines.extend([f"- {item}" for item in warnings] or ["- None"])
    lines.append("")
    lines.append("## Sources")
    for group in ["model", "search", "macro", "company"]:
        lines.append(f"### {group}")
        payload = result.get(group, {})
        if isinstance(payload, dict):
            for name, item in payload.items():
                if isinstance(item, dict):
                    lines.append(f"- {name}: {item.get('status', 'ok' if item.get('ok') else 'failed')} ({item.get('returned_hits', item.get('record_count', ''))})")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
