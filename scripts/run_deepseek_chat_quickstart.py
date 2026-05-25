"""Quickstart: verify DeepSeek API connectivity then launch chat UI.

Usage:
    python scripts/run_deepseek_chat_quickstart.py

Opens http://127.0.0.1:8787 in browser after connectivity check passes.
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.web_ui import run_ui_server
from src.models import ModelAdapter


def main() -> int:
    parser = argparse.ArgumentParser(description="DeepSeek quickstart: verify API + launch chat UI.")
    parser.add_argument("--config-path", default="configs/model_backends.yaml")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--output-dir", default="data/outputs/multi_agent")
    parser.add_argument("--report-dir", default="data/reports/multi_agent")
    parser.add_argument("--memory-root", default="memory/chat")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open browser")
    args = parser.parse_args()

    # ── Step 1: DeepSeek API connectivity check ─────────────────────────
    print("=" * 60)
    print("Step 1/2: Verifying DeepSeek API connectivity...")
    print("=" * 60)

    adapter = ModelAdapter.from_config(config_path=args.config_path)
    print(f"  provider  : {adapter.provider}")
    print(f"  model     : {adapter.model_name}")
    print(f"  endpoint  : {adapter.endpoint_url}")
    print(f"  api_key   : {'*** set ***' if adapter.api_key else 'MISSING'}")

    if not adapter.api_key:
        print("\n  ERROR: DEEPSEEK_API_KEY not found.")
        print("  Set it in .env or as an environment variable.\n")
        return 1

    response = adapter.generate(
        prompt="Reply in one sentence: DeepSeek API connectivity check passed.",
        system_prompt="You are a helpful assistant. Keep your answer concise.",
    )
    if not response.success:
        print(f"\n  ERROR: API call failed — {response.error}\n")
        return 1

    print(f"\n  API response: {response.content.strip()}")
    print("\n  [OK] DeepSeek API is connected and working.\n")

    # ── Step 2: Launch Chat UI ───────────────────────────────────────────
    print("=" * 60)
    print("Step 2/2: Starting FinSight Chat UI...")
    print("=" * 60)

    server, url = run_ui_server(
        host=args.host,
        port=args.port,
        output_dir=args.output_dir,
        report_dir=args.report_dir,
        config_path=args.config_path,
        memory_root=args.memory_root,
    )

    print(f"\n  [OK] Chat UI running at: {url}")
    print()
    print("  =" * 30)
    print("  OPEN IN YOUR BROWSER:")
    print(f"    {url}")
    print()
    print("  TRY TYPING:")
    print("  - generate 600519.SS latest company report")
    print("  - generate AMD latest company report")
    print("  - 600519.SS 2025Q4 report")
    print("  =" * 30)
    print()

    if not args.no_browser:
        try:
            webbrowser.open(url)
            print("  (Browser opened automatically)")
        except Exception:
            pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
