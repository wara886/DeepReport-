"""Smoke-test the local Chat UI API through /api/chat."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from threading import Thread
from urllib import request
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.web_ui import run_ui_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run /api/chat smoke tests for the DeepReport++ workbench.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--config-path", default="configs/model_backends.yaml")
    parser.add_argument("--output-dir", default="eval_outputs/chat_ui_smoke/company/outputs")
    parser.add_argument("--report-dir", default="eval_outputs/chat_ui_smoke/company/reports")
    parser.add_argument("--memory-root", default="eval_outputs/chat_ui_smoke/memory")
    parser.add_argument("--raw-data-root", default="data/raw/real_data")
    parser.add_argument("--symbol", default="AAPL")
    parser.add_argument("--period", default="2025Q4")
    parser.add_argument("--skip-report-run", action="store_true")
    args = parser.parse_args(argv)

    server, url = run_ui_server(
        host=args.host,
        port=args.port,
        output_dir=args.output_dir,
        report_dir=args.report_dir,
        config_path=args.config_path,
        raw_data_root=args.raw_data_root,
        memory_root=args.memory_root,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        responses = [
            _post_chat(
                url,
                {
                    "message": "我喜欢简洁回答，以后默认用中文。",
                    "session_id": "chat_smoke",
                    "user_id": "smoke_user",
                    "symbol": args.symbol,
                    "period": args.period,
                    "memory_enabled": True,
                },
            ),
            _post_chat(
                url,
                {
                    "message": f"请根据证据和引用解释 {args.symbol} {args.period} 的收入表现。",
                    "session_id": "chat_smoke",
                    "user_id": "smoke_user",
                    "symbol": args.symbol,
                    "period": args.period,
                    "memory_enabled": True,
                },
            ),
        ]
        if not args.skip_report_run:
            responses.append(
                _post_chat(
                    url,
                    {
                        "message": f"请生成 {args.symbol} {args.period} 公司研报。",
                        "session_id": "chat_smoke_report",
                        "user_id": "smoke_user",
                        "symbol": args.symbol,
                        "period": args.period,
                        "memory_enabled": True,
                        "allow_report_run": True,
                        "fast": True,
                        "engines": ["local_real_data"],
                    },
                )
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)

    summary = _summarize(responses=responses, memory_root=Path(args.memory_root))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["passed"] else 2


def _post_chat(url: str, payload: dict) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        f"{url}/api/chat",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _summarize(responses: list[dict], memory_root: Path) -> dict:
    modes = [response.get("mode") for response in responses]
    traces = [stage.get("stage") for response in responses for stage in response.get("tool_trace", []) if isinstance(stage, dict)]
    report_response = next((response for response in responses if response.get("mode") == "report_run"), {})
    checks = {
        "chat_mode": "chat" in modes,
        "rag_mode": "rag" in modes,
        "memory_enabled": all(response.get("memory_used", {}).get("enabled") is True for response in responses),
        "trace_returned": all(response.get("tool_trace") for response in responses),
        "report_route": not report_response or any(item.get("detail") == "start_multi_agent_report_run" for item in report_response.get("tool_trace", [])),
        "report_verified_field": not report_response or "verification_passed" in dict(report_response.get("result", {})),
        "preference_memory_written": any((memory_root / "users").glob("*.json")),
        "long_term_memory_written": any((memory_root / "long_term").glob("*.json")),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "modes": modes,
        "trace_stages": traces,
        "response_count": len(responses),
        "memory_root": str(memory_root),
    }


if __name__ == "__main__":
    raise SystemExit(main())
