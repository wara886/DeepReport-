"""Smoke test for the DeepSeek-backed model adapter."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.models import ModelAdapter


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a minimal DeepSeek model smoke test.")
    parser.add_argument("--config-path", default="configs/model_backends.yaml")
    parser.add_argument("--prompt", default="用一句话说明你已经可以作为金融多 Agent 的底层模型。")
    args = parser.parse_args()

    adapter = ModelAdapter.from_config(config_path=args.config_path)
    print(f"provider={adapter.provider}")
    print(f"model={adapter.model_name}")
    print(f"endpoint={adapter.endpoint_url}")

    response = adapter.generate(
        prompt=args.prompt,
        system_prompt="你是一个金融研究多智能体系统中的模型后端，请简洁回答。",
    )
    if not response.success:
        print(f"error={response.error}")
        return 1

    print(response.content.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
