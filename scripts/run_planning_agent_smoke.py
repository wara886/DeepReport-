"""Smoke test for the DeepSeek-backed PlanningAgent."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.planning_agent import PlanningAgent


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate one financial multi-agent task plan.")
    parser.add_argument("--config-path", default="configs/model_backends.yaml")
    parser.add_argument("--topic", default="分析 AAPL 2025Q4 财务表现，并生成带引用的研究报告")
    parser.add_argument("--output-path", default="data/outputs/task_plan.json")
    args = parser.parse_args()

    agent = PlanningAgent.from_config(config_path=args.config_path, fallback_on_error=False)
    plan = agent.build_research_plan(
        research_topic=args.topic,
        requirements=[
            "覆盖收入、利润、现金流、风险、估值和近期新闻",
            "所有关键结论必须能追溯到证据或数据来源",
            "输出 Markdown 和 HTML 报告",
        ],
        output_format="markdown and html report with citations",
    )

    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"task_count": len(plan["tasks"]), "output_path": str(output_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
