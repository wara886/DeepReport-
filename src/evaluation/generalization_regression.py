"""Generalization regression runner for company report quality checks."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
import random
import re
from typing import Any, Dict, Iterable, List

from src.agents.multi_agent_orchestrator import MultiAgentOrchestrator
from src.evaluation.delivery_pipeline import run_delivery_quality_pipeline
from src.utils.periods import latest_completed_period
from scripts.check_runtime_sources import run_checks


SENTINEL_CASES = [
    {"symbol": "600519.SS", "period": "2025Q4", "bucket": "cn_a_consumer"},
    {"symbol": "AMD", "period": "2025Q4", "bucket": "us_technology"},
    {"symbol": "0700.HK", "period": "latest", "bucket": "hk_internet"},
]

REGRESSION_POOL = [
    {"symbol": "600519.SS", "period": "2025Q4", "bucket": "cn_a_consumer"},
    {"symbol": "000651.SZ", "period": "2025Q4", "bucket": "cn_a_manufacturing"},
    {"symbol": "600036.SS", "period": "2025Q4", "bucket": "cn_a_financial"},
    {"symbol": "AMD", "period": "2025Q4", "bucket": "us_technology"},
    {"symbol": "AAPL", "period": "2025Q4", "bucket": "us_consumer_technology"},
    {"symbol": "JPM", "period": "2025Q4", "bucket": "us_financial"},
    {"symbol": "0700.HK", "period": "latest", "bucket": "hk_internet"},
    {"symbol": "0005.HK", "period": "latest", "bucket": "hk_financial"},
    {"symbol": "1109.HK", "period": "latest", "bucket": "hk_real_estate"},
]


@dataclass(frozen=True)
class RegressionCase:
    """A ticker-period pair used as a quality sentinel, not special logic."""

    symbol: str
    period: str
    bucket: str

    def to_dict(self) -> Dict[str, str]:
        return {"symbol": self.symbol, "period": self.period, "bucket": self.bucket}


def select_regression_cases(random_count: int = 5, seed: int = 7) -> List[RegressionCase]:
    """Return fixed sentinels plus random samples across markets and industries."""

    sentinels = [_case(item) for item in SENTINEL_CASES]
    sentinel_keys = {(item.symbol, item.period) for item in sentinels}
    candidates = [
        _case(item)
        for item in REGRESSION_POOL
        if (_case(item).symbol, _case(item).period) not in sentinel_keys
    ]
    rng = random.Random(seed)
    rng.shuffle(candidates)
    return sentinels + candidates[: max(0, int(random_count))]


def run_generalization_regression(
    output_root: str | Path = "eval_outputs/generalization_regression",
    random_count: int = 5,
    seed: int = 7,
    fast: bool = True,
    execution_mode: str = "dynamic",
    enable_remote_data: bool = False,
    require_deepseek: bool = True,
    data_source_config_path: str = "configs/data_sources.yaml",
) -> Dict[str, Any]:
    """Run selected cases and write a compact pass/fail summary."""

    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    preflight = run_regression_preflight(
        require_deepseek=require_deepseek,
        config_path=data_source_config_path,
    )
    if preflight.get("status") == "blocked":
        summary = {
            "schema_version": "generalization_regression.v1",
            "status": "blocked",
            "blocked_reason": preflight.get("blocked_reason", "preflight_blocked"),
            "preflight": preflight,
            "case_count": 0,
            "passed_count": 0,
            "cases": [],
        }
        (root / "generalization_regression_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return summary

    cases = select_regression_cases(random_count=random_count, seed=seed)
    rows: List[Dict[str, Any]] = []
    for case in cases:
        run_dir = root / _safe_case_name(case)
        output_dir = run_dir / "company" / "outputs"
        report_dir = run_dir / "company" / "reports"
        orchestrator = MultiAgentOrchestrator(output_dir=str(output_dir), report_dir=str(report_dir))
        run_period = latest_completed_period(date.today()) if case.period == "LATEST" else case.period
        result = orchestrator.run(
            research_topic=f"Generate {case.symbol} {run_period} company stock research report",
            symbol=case.symbol,
            period=run_period,
            execution_mode=execution_mode,
            fast=fast,
            enable_remote_data=enable_remote_data,
            data_source_config_path=data_source_config_path,
        )
        quality = run_delivery_quality_pipeline(output_dir, report_dir, memory_enabled=False)
        rows.append(
            {
                "case": case.to_dict(),
                "run_dir": str(run_dir),
                "objective_pass": quality.get("quality_report", {}).get("objective_pass"),
                "delivery_pass": quality.get("delivery_gate", {}).get("delivery_pass"),
                "result_paths": result,
            }
        )
    summary = {
        "schema_version": "generalization_regression.v1",
        "status": "completed",
        "preflight": preflight,
        "case_count": len(rows),
        "passed_count": sum(1 for row in rows if row.get("delivery_pass") is True),
        "cases": rows,
    }
    (root / "generalization_regression_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def run_regression_preflight(
    require_deepseek: bool = True,
    config_path: str = "configs/data_sources.yaml",
) -> Dict[str, Any]:
    """Check runtime sources before expensive real-company regression."""

    health = run_checks(config_path=config_path)
    deepseek = health.get("model", {}).get("deepseek", {}) if isinstance(health.get("model"), dict) else {}
    deepseek_ok = bool(deepseek.get("ok"))
    blocked = bool(require_deepseek and not deepseek_ok)
    return {
        "schema_version": "generalization_regression_preflight.v1",
        "status": "blocked" if blocked else "ok",
        "blocked_reason": "deepseek_unavailable" if blocked else "",
        "deepseek_required": bool(require_deepseek),
        "deepseek_ok": deepseek_ok,
        "runtime_source_health": health,
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run fixed and random company-report generalization checks.")
    parser.add_argument("--output-root", default="eval_outputs/generalization_regression")
    parser.add_argument("--random-count", type=int, default=5)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--full", action="store_true", help="Use default profile instead of fast profile.")
    parser.add_argument("--remote-data", action="store_true", help="Allow configured remote data adapters.")
    parser.add_argument("--allow-missing-deepseek", action="store_true", help="Do not block regression when DeepSeek preflight fails.")
    parser.add_argument("--data-source-config", default="configs/data_sources.yaml")
    args = parser.parse_args(list(argv) if argv is not None else None)
    summary = run_generalization_regression(
        output_root=args.output_root,
        random_count=args.random_count,
        seed=args.seed,
        fast=not args.full,
        enable_remote_data=bool(args.remote_data),
        require_deepseek=not bool(args.allow_missing_deepseek),
        data_source_config_path=args.data_source_config,
    )
    print(json.dumps({"status": summary.get("status"), "case_count": summary["case_count"], "passed_count": summary["passed_count"]}, ensure_ascii=False))
    return 0


def _case(item: Dict[str, str]) -> RegressionCase:
    return RegressionCase(symbol=str(item["symbol"]).upper(), period=str(item["period"]).upper(), bucket=str(item["bucket"]))


def _safe_case_name(case: RegressionCase) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", f"{case.symbol}_{case.period}_{case.bucket}")
