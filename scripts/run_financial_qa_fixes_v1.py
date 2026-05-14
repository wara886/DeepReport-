"""Re-run JPM latest report after P1 fixes, and also run a non-JPM real-time-data report for validation."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.multi_agent_orchestrator import MultiAgentOrchestrator


def run_report(
    symbol: str,
    period: str,
    tag: str,
    engines: list[str],
    execution_mode: str = "dynamic",
    fast: bool = True,
    config_path: str = "configs/model_backends.yaml",
    raw_data_root: str = "data/raw/real_data",
) -> dict:
    output_dir = f"data/outputs/{tag}"
    report_dir = f"data/reports/{tag}"
    orchestrator = MultiAgentOrchestrator(
        output_dir=output_dir,
        report_dir=report_dir,
        config_path=config_path,
        raw_data_root=raw_data_root,
    )
    topic = f"分析 {symbol} {period} 财务表现，并生成带引用的研究报告"
    t0 = time.perf_counter()
    result = orchestrator.run(
        research_topic=topic,
        symbol=symbol,
        period=period,
        execution_mode=execution_mode,
        fast=fast,
        search_engines=engines,
    )
    elapsed = round(time.perf_counter() - t0, 1)
    return {
        "symbol": symbol,
        "period": period,
        "tag": tag,
        "elapsed_sec": elapsed,
        "output_dir": output_dir,
        "report_dir": report_dir,
        "result": result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run QA verification for DeepReport+ fixes.")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--period", default="latest")
    parser.add_argument("--tag", required=True)
    parser.add_argument(
        "--engines",
        default="local_real_data,sec_companyfacts,yahoo_finance,tavily,local_evidence",
    )
    parser.add_argument("--execution-mode", default="dynamic", choices=["dynamic", "static"])
    parser.add_argument("--fast", action="store_true", default=True)
    args = parser.parse_args()

    engines = [item.strip() for item in args.engines.split(",") if item.strip()]
    summary = run_report(
        symbol=args.symbol.upper(),
        period=args.period,
        tag=args.tag,
        engines=engines,
        execution_mode=args.execution_mode,
        fast=args.fast,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
