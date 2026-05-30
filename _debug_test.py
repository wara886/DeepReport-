"""Debug the failing test response."""
import json
import threading
import sys
from pathlib import Path
from urllib import request, error
from datetime import date

# Inline model config
def write_config(tmp_path):
    config = Path(tmp_path) / "model_backends.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        """
agent_model:
  provider: deepseek
  model_name: deepseek-test
  base_url: https://api.deepseek.com
  api_key: ""
  timeout: 1
  retry: 0
  max_tokens: 256
  temperature: 0.1
""".strip(),
        encoding="utf-8",
    )
    return config

import tempfile
tmp = tempfile.mktemp()
print(f"Temp dir: {tmp}")

from src.app.web_ui import run_ui_server

import importlib
import src.app.web_ui
importlib.reload(src.app.web_ui)
from src.app.web_ui import MultiAgentOrchestrator, run_delivery_quality_pipeline

# Patch
class FakeOrch:
    def __init__(self, output_dir, report_dir, **kwargs):
        self.output_dir = Path(tmp) / "outputs"
        self.report_dir = Path(tmp) / "reports"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.report_dir.mkdir(parents=True, exist_ok=True)

    def run(self, **kwargs):
        (self.output_dir / "citations.json").write_text("[]", encoding="utf-8")
        (self.output_dir / "run_summary.json").write_text(
            json.dumps({"verification_passed": True, "symbol": kwargs["symbol"], "period": kwargs["period"], "search_engines": kwargs["search_engines"]}),
            encoding="utf-8",
        )
        (self.output_dir / "verification_report.json").write_text('{"passed": true}', encoding="utf-8")
        (self.output_dir / "task_trace.jsonl").write_text('{"agent":"fake","status":"completed"}\n', encoding="utf-8")
        (self.report_dir / "report.md").write_text("# Fake report", encoding="utf-8")
        return {"verification_passed": True, "report_md": str(self.report_dir / "report.md")}

src.app.web_ui.MultiAgentOrchestrator = FakeOrch
src.app.web_ui.run_delivery_quality_pipeline = lambda *a, **kw: {
    "quality_report": {"objective_pass": True},
    "llm_quality_review": {"llm_review_pass": True},
    "delivery_gate": {"delivery_pass": True},
    "top_quality_issues": [],
}

config = write_config(Path(tmp))
server, url = run_ui_server(
    port=0,
    output_dir=str(Path(tmp) / "outputs"),
    report_dir=str(Path(tmp) / "reports"),
    config_path=str(config),
    memory_root=str(Path(tmp) / "memory"),
)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    payload = json.dumps(
        {
            "message": "请生成贵州茅台 2025Q4 公司研报",
            "memory_enabled": True,
            "allow_report_run": True,
            "enable_remote_data": True,
        }
    ).encode("utf-8")
    req = request.Request(
        f"{url}/api/chat",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with request.urlopen(req, timeout=10) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    print(f"\nResponse mode: {body.get('mode')}")
    print(f"Keys in response: {sorted(body.keys())}")
    if "tool_trace" in body:
        print(f"tool_trace: {json.dumps(body['tool_trace'], ensure_ascii=False, indent=2)}")
    else:
        print("NO tool_trace in response!")
    if "result" in body:
        print(f"result status: {body['result'].get('status')}")
    print(f"parsed_task: {json.dumps(body.get('parsed_task', {}), ensure_ascii=False, indent=2)}")
except Exception as e:
    print(f"Error: {e}")
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)
