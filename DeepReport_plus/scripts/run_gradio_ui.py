"""Gradio web UI for DeepReport+ financial multi-agent workflow."""

from __future__ import annotations

import argparse
import json
import sys
import threading
from pathlib import Path
from typing import Any, Dict, Generator, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import gradio as gr
except ImportError:
    print("Gradio not installed. Run: pip install gradio>=4.0")
    sys.exit(1)

from src.agents.multi_agent_orchestrator import MultiAgentOrchestrator

DEFAULT_OUTPUT_DIR = "data/outputs/multi_agent"
DEFAULT_REPORT_DIR = "data/reports/multi_agent"
DEFAULT_ENGINES = "yahoo_finance,sec_companyfacts,tavily,serper"
DEFAULT_TOPIC = "Analyze MSFT latest quarter company stock research report with citations, charts, valuation and risk review"

_run_lock = threading.Lock()

APP_CSS = """
:root {
  --dr-bg: #f4f6f8;
  --dr-panel: #ffffff;
  --dr-panel-soft: #f8fafc;
  --dr-ink: #111827;
  --dr-muted: #5f6b7a;
  --dr-line: #d9e0e7;
  --dr-accent: #0f766e;
  --dr-accent-strong: #115e59;
  --dr-warm: #a16207;
}
html,
body,
gradio-app,
.gradio-container {
  background: var(--dr-bg) !important;
}
.gradio-container {
  max-width: none !important;
  width: 100vw !important;
  min-height: 100vh !important;
  margin: 0 !important;
  padding: 22px 28px 34px !important;
  background: var(--dr-bg) !important;
  color: var(--dr-ink) !important;
  font-family: Inter, "Segoe UI", "Noto Sans SC", "Microsoft YaHei UI", "Microsoft YaHei", Arial, sans-serif !important;
}
.gradio-container > .main,
.gradio-container .contain,
.gradio-container .wrap {
  max-width: none !important;
}
.dr-hero {
  padding: 6px 2px 18px;
  border-bottom: 1px solid var(--dr-line);
  margin-bottom: 18px;
}
.dr-kicker {
  color: var(--dr-accent);
  font-size: 12px;
  font-weight: 760;
  letter-spacing: .04em;
  text-transform: uppercase;
}
.dr-hero h1 {
  margin: 4px 0 7px;
  font-size: 28px;
  line-height: 1.2;
  color: var(--dr-ink);
  letter-spacing: 0;
}
.dr-hero p {
  margin: 0;
  color: var(--dr-muted);
  font-size: 14px;
}
.gradio-container label,
.gradio-container .block-title,
.gradio-container .form label {
  color: var(--dr-ink) !important;
  font-weight: 700 !important;
}
.gradio-container textarea,
.gradio-container input,
.gradio-container .wrap,
.gradio-container .block {
  border-radius: 8px !important;
}
.gradio-container textarea,
.gradio-container input {
  font-family: Inter, "Segoe UI", "Noto Sans SC", "Microsoft YaHei UI", "Microsoft YaHei", Arial, sans-serif !important;
}
.gradio-container .prose,
.gradio-container .markdown,
.gradio-container .output-markdown {
  font-family: Inter, "Segoe UI", "Noto Sans SC", "Microsoft YaHei UI", "Microsoft YaHei", Arial, sans-serif !important;
  line-height: 1.78 !important;
  color: var(--dr-ink) !important;
}
.gradio-container .prose h1,
.gradio-container .prose h2,
.gradio-container .prose h3,
.gradio-container .markdown h1,
.gradio-container .markdown h2,
.gradio-container .markdown h3 {
  letter-spacing: 0 !important;
  color: var(--dr-ink) !important;
}
.gradio-container table {
  font-size: 13px !important;
}
.gradio-container button.primary {
  background: var(--dr-accent) !important;
  border-color: var(--dr-accent) !important;
}
.gradio-container button.primary:hover {
  background: var(--dr-accent-strong) !important;
}
.gradio-container .tabs {
  border-bottom-color: var(--dr-line) !important;
}
.gradio-container code,
.gradio-container pre {
  font-family: "Cascadia Code", "SFMono-Regular", Consolas, monospace !important;
}
"""


def _load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _load_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def run_report(
    topic: str,
    symbol: str,
    period: str,
    engines: str,
    execution_mode: str,
    fast: bool,
    output_dir: str,
    report_dir: str,
) -> Generator[tuple, None, None]:
    if not _run_lock.acquire(blocking=False):
        yield (
            "另一个任务正在运行，请稍候...",
            "", "", "", "", gr.update(value=None),
        )
        return

    status_lines: List[str] = []

    def log(msg: str) -> None:
        status_lines.append(msg)

    try:
        log(f"启动多智能体任务: {symbol} / {period}")
        log(f"搜索引擎: {engines}")
        log(f"执行模式: {execution_mode} | 快速模式: {fast}")
        yield (_fmt_status(status_lines), "", "", "", "", "", gr.update(value=None))

        engine_list = [e.strip() for e in engines.split(",") if e.strip()] or None
        orchestrator = MultiAgentOrchestrator(
            output_dir=output_dir,
            report_dir=report_dir,
            config_path="configs/model_backends.yaml",
            raw_data_root="data/raw/real_data",
        )

        log("Orchestrator 初始化完成，开始运行...")
        yield (_fmt_status(status_lines), "", "", "", "", "", gr.update(value=None))

        result = orchestrator.run(
            research_topic=topic,
            symbol=symbol,
            period=period,
            execution_mode=execution_mode,
            fast=fast,
            search_engines=engine_list,
        )

        log("运行完成，正在读取产物...")
        yield (_fmt_status(status_lines), "", "", "", "", "", gr.update(value=None))

        out_root = Path(output_dir)
        rep_root = Path(report_dir)

        summary = _load_json(out_root / "run_summary.json", {})
        search_meta = _load_json(out_root / "search_meta.json", {})
        analysis_artifacts = _load_json(out_root / "analysis_artifacts.json", {})
        multimodal = _load_json(out_root / "multimodal_consistency.json", {})
        citations = _load_json(out_root / "citations.json", [])
        report_md = _load_text(rep_root / "report.md")
        report_html_path = rep_root / "report.html"

        summary_md = _build_summary_md(summary)
        diagnostics_md = _build_diagnostics_md(
            summary=summary,
            search_meta=search_meta,
            analysis_artifacts=analysis_artifacts,
            multimodal=multimodal,
        )
        citations_md = _build_citations_md(citations)
        result_json = json.dumps(result, ensure_ascii=False, indent=2)

        log("完成！")

        html_file = str(report_html_path) if report_html_path.exists() else None
        yield (
            _fmt_status(status_lines),
            summary_md,
            diagnostics_md,
            report_md,
            citations_md,
            result_json,
            gr.update(value=html_file, visible=html_file is not None),
        )

    except Exception as exc:
        log(f"错误: {exc}")
        yield (_fmt_status(status_lines, error=True), "", "", "", "", str(exc), gr.update(value=None))
    finally:
        _run_lock.release()


def load_latest(output_dir: str, report_dir: str) -> tuple:
    out_root = Path(output_dir)
    rep_root = Path(report_dir)

    summary = _load_json(out_root / "run_summary.json", {})
    search_meta = _load_json(out_root / "search_meta.json", {})
    analysis_artifacts = _load_json(out_root / "analysis_artifacts.json", {})
    multimodal = _load_json(out_root / "multimodal_consistency.json", {})
    citations = _load_json(out_root / "citations.json", [])
    report_md = _load_text(rep_root / "report.md")
    report_html_path = rep_root / "report.html"

    if not summary and not report_md:
        return ("暂无历史结果。", "", "", "", "", "", gr.update(value=None))

    summary_md = _build_summary_md(summary)
    diagnostics_md = _build_diagnostics_md(
        summary=summary,
        search_meta=search_meta,
        analysis_artifacts=analysis_artifacts,
        multimodal=multimodal,
    )
    citations_md = _build_citations_md(citations)
    html_file = str(report_html_path) if report_html_path.exists() else None

    return (
        "已读取最近一次输出。",
        summary_md,
        diagnostics_md,
        report_md,
        citations_md,
        "",
        gr.update(value=html_file, visible=html_file is not None),
    )


def _fmt_status(lines: List[str], error: bool = False) -> str:
    prefix = "ERROR: " if error else ""
    return prefix + "\n".join(lines)


def _build_summary_md(summary: Dict[str, Any]) -> str:
    if not summary:
        return "_暂无摘要数据。_"
    lines = ["| 指标 | 值 |", "|---|---|"]
    for k, v in summary.items():
        lines.append(f"| {k} | {v} |")
    return "\n".join(lines)


def _build_citations_md(citations: List[Dict[str, Any]]) -> str:
    if not citations:
        return "_暂无引用数据。_"
    lines = ["| 证据ID | 标题 | 类型 | 来源 |", "|---|---|---|---|"]
    for r in citations[:50]:
        url = r.get("source_url", "")
        src = f"[链接]({url})" if url else ""
        lines.append(
            f"| {r.get('evidence_id','')} | {r.get('title','')} | {r.get('source_type','')} | {src} |"
        )
    return "\n".join(lines)


def _build_diagnostics_md(
    summary: Dict[str, Any],
    search_meta: Dict[str, Any],
    analysis_artifacts: Dict[str, Any],
    multimodal: Dict[str, Any],
) -> str:
    statement_view = analysis_artifacts.get("statement_view", {}) if isinstance(analysis_artifacts, dict) else {}
    financial_metrics = analysis_artifacts.get("financial_metrics", {}) if isinstance(analysis_artifacts, dict) else {}
    tables = analysis_artifacts.get("tables", []) if isinstance(analysis_artifacts, dict) else []
    valuation = analysis_artifacts.get("valuation", {}) if isinstance(analysis_artifacts, dict) else {}
    coverage = statement_view.get("coverage", {}) if isinstance(statement_view, dict) else {}
    metric_coverage = financial_metrics.get("coverage", {}) if isinstance(financial_metrics, dict) else {}
    engine_meta = search_meta.get("engine_meta", {}) if isinstance(search_meta, dict) else {}

    rows = [
        ("实时数据源", ", ".join(summary.get("search_engines", []) or search_meta.get("engines", []) or []) or "-"),
        ("检索返回证据", summary.get("evidence_count", "-")),
        ("可验证结论", summary.get("claim_count", "-")),
        ("图表数量", summary.get("chart_count", "-")),
        ("三表视图", "已生成" if coverage.get("has_three_statement_view") else "未生成"),
        ("三表行项目", coverage.get("line_item_count", 0)),
        ("结构化指标", financial_metrics.get("metric_count", 0) if isinstance(financial_metrics, dict) else 0),
        ("核心指标血缘", "具备" if metric_coverage.get("has_core_metric_lineage") else "不足"),
        ("表格数量", len(tables) if isinstance(tables, list) else 0),
        ("估值模型", "已生成" if valuation.get("valuation_available") else f"未生成: {valuation.get('error', '缺少输入')}"),
        ("多模态校验", "通过" if multimodal.get("passed") else "未通过/未触发"),
    ]
    lines = ["### 本次后台数据诊断", "", "| 项目 | 状态 |", "|---|---|"]
    for k, v in rows:
        lines.append(f"| {k} | {v} |")

    if engine_meta:
        lines.extend(["", "### 搜索源命中", "", "| 来源 | 命中/返回 | 备注 |", "|---|---:|---|"])
        for name, meta in engine_meta.items():
            if not isinstance(meta, dict):
                continue
            count = meta.get("result_count", "-")
            note = meta.get("mode") or meta.get("search_depth") or ""
            lines.append(f"| {name} | {count} | {note} |")

    missing = []
    if not coverage.get("has_three_statement_view"):
        missing.append("三表摘要需要结构化财务报表行项目；本次实时网页摘要没有抽出资产负债表、利润表、现金流量表的可复算行。")
    if not metric_coverage.get("has_core_metric_lineage"):
        missing.append("核心指标血缘不足；收入、净利润、毛利率、自由现金流没有以统一字段进入 `financial_metrics.json`。")
    if valuation and not valuation.get("valuation_available"):
        missing.append(f"估值未生成：{valuation.get('error', '缺少目标财务数据')}")
    if missing:
        lines.extend(["", "### 为什么有些章节为空", ""])
        lines.extend([f"- {item}" for item in missing])
    return "\n".join(lines)


def build_ui(output_dir: str, report_dir: str) -> gr.Blocks:
    with gr.Blocks(title="DeepReport+ 金融研究工作台") as demo:
        gr.HTML(
            """
            <section class="dr-hero">
              <div class="dr-kicker">Realtime Financial Multi-Agent</div>
              <h1>DeepReport+ 金融研究工作台</h1>
              <p>实时检索、证据归因、图表与报告产物统一查看。默认数据源为 Yahoo Finance、Tavily、Serper。</p>
            </section>
            """
        )

        with gr.Row():
            with gr.Column(scale=1):
                topic = gr.Textbox(label="研究任务", value=DEFAULT_TOPIC, lines=3)
                with gr.Row():
                    symbol = gr.Textbox(label="股票代码", value="MSFT")
                    period = gr.Textbox(label="期间", value="latest")
                engines = gr.Textbox(label="搜索/数据源 (逗号分隔)", value=DEFAULT_ENGINES)
                with gr.Row():
                    execution_mode = gr.Radio(
                        ["dynamic", "static"], label="执行模式", value="dynamic"
                    )
                    fast = gr.Checkbox(label="快速模式", value=True)
                with gr.Accordion("高级路径设置", open=False):
                    out_dir_input = gr.Textbox(label="output-dir", value=output_dir)
                    rep_dir_input = gr.Textbox(label="report-dir", value=report_dir)
                with gr.Row():
                    run_btn = gr.Button("生成多智能体研究报告", variant="primary")
                    refresh_btn = gr.Button("读取最近结果", variant="secondary")
                status_box = gr.Textbox(label="运行状态", lines=6, interactive=False)

            with gr.Column(scale=2):
                with gr.Tabs():
                    with gr.Tab("总览"):
                        summary_md = gr.Markdown()
                    with gr.Tab("数据诊断"):
                        diagnostics_md = gr.Markdown()
                    with gr.Tab("报告 (Markdown)"):
                        report_md = gr.Markdown()
                    with gr.Tab("引用"):
                        citations_md = gr.Markdown()
                    with gr.Tab("原始 JSON"):
                        raw_json = gr.Code(language="json", label="result JSON")
                    with gr.Tab("报告 HTML"):
                        html_file = gr.File(label="下载 report.html", visible=False)

        outputs = [status_box, summary_md, diagnostics_md, report_md, citations_md, raw_json, html_file]

        run_btn.click(
            fn=run_report,
            inputs=[topic, symbol, period, engines, execution_mode, fast, out_dir_input, rep_dir_input],
            outputs=outputs,
        )

        refresh_btn.click(
            fn=load_latest,
            inputs=[out_dir_input, rep_dir_input],
            outputs=outputs,
        )

    return demo


def main() -> int:
    parser = argparse.ArgumentParser(description="Run DeepReport+ Gradio UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report-dir", default=DEFAULT_REPORT_DIR)
    parser.add_argument("--share", action="store_true", help="Create a public Gradio share link.")
    args = parser.parse_args()

    demo = build_ui(output_dir=args.output_dir, report_dir=args.report_dir)
    print(f"Starting DeepReport+ Gradio UI at http://{args.host}:{args.port}")
    demo.launch(
        server_name=args.host,
        server_port=args.port,
        share=args.share,
        css=APP_CSS,
        theme=gr.themes.Soft(primary_hue="teal", neutral_hue="slate"),
        inbrowser=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
