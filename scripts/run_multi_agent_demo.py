"""Run the DeepSeek-backed financial multi-agent demo."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.multi_agent_orchestrator import MultiAgentOrchestrator


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a visible financial multi-agent workflow.")
    parser.add_argument("--topic", default="分析 AAPL 2025Q4 财务表现，并生成带引用的研究报告")
    parser.add_argument("--symbol", default="AAPL")
    parser.add_argument("--period", default="2025Q4")
    parser.add_argument("--config-path", default="configs/model_backends.yaml")
    parser.add_argument("--app-config-path", default="configs/app.yaml")
    parser.add_argument("--raw-data-root", default="data/raw/real_data")
    parser.add_argument("--output-dir", default="data/outputs/multi_agent")
    parser.add_argument("--report-dir", default="data/reports/multi_agent")
    parser.add_argument("--execution-mode", default="dynamic", choices=["dynamic", "static"])
    parser.add_argument("--fast", action="store_true", help="Reduce search/context size and skip optional LLM extraction.")
    parser.add_argument("--memory-enabled", action="store_true", help="Inject durable memory context and persist run memory artifacts.")
    parser.add_argument("--memory-root", default="", help="Override durable memory root. Defaults to configs/app.yaml.")
    parser.add_argument(
        "--retrieval-ranking-mode",
        default="hybrid_rerank",
        choices=["bm25", "vector", "hybrid", "reranker", "hybrid_rerank"],
        help="Ranking mode for local_evidence retrieval.",
    )
    parser.add_argument(
        "--engines",
        default="",
        help="Comma-separated search engines, e.g. local_real_data,yahoo_finance,tavily,local_evidence.",
    )
    args = parser.parse_args()

    orchestrator = MultiAgentOrchestrator(
        output_dir=args.output_dir,
        report_dir=args.report_dir,
        config_path=args.config_path,
        raw_data_root=args.raw_data_root,
        app_config_path=args.app_config_path,
        memory_enabled=True if args.memory_enabled else None,
        memory_root=args.memory_root or None,
    )
    result = orchestrator.run(
        research_topic=args.topic,
        symbol=args.symbol,
        period=args.period,
        execution_mode=args.execution_mode,
        fast=args.fast,
        search_engines=[item.strip() for item in args.engines.split(",") if item.strip()] or None,
        retrieval_ranking_mode=args.retrieval_ranking_mode,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
