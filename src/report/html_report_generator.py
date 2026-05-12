"""Professional static HTML report generator."""

from __future__ import annotations

import base64
from html import escape
import mimetypes
from pathlib import Path
import re
from typing import Any, Dict, List


def render_professional_html_report(
    markdown: str,
    title: str,
    charts: List[Dict[str, Any]] | None = None,
    citations: List[Dict[str, Any]] | None = None,
) -> str:
    charts = charts or []
    citations = citations or []
    body = _markdown_to_html(markdown)
    chart_blocks = _render_chart_blocks(charts)
    citation_count = len(citations)
    chart_count = len(charts)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{
      --ink: #172026;
      --muted: #66736d;
      --line: #d7dfda;
      --soft: #f5f7f3;
      --accent: #0f766e;
      --panel: #ffffff;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Arial, "PingFang SC", "Microsoft YaHei", sans-serif; color: var(--ink); background: var(--soft); line-height: 1.68; }}
    header {{ padding: 28px 34px 20px; background: #ffffff; border-bottom: 1px solid var(--line); }}
    header h1 {{ margin: 0 0 10px; font-size: 28px; letter-spacing: 0; }}
    .meta {{ display: flex; gap: 10px; flex-wrap: wrap; color: var(--muted); font-size: 13px; }}
    .badge {{ border: 1px solid #b7d8d2; color: #115e59; background: #eef9f6; padding: 4px 8px; border-radius: 999px; font-weight: 700; }}
    main {{ max-width: 1480px; margin: 0 auto; padding: 22px; }}
    section.report-section, .chart-panel {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 18px 20px; margin: 14px 0; }}
    h2 {{ margin: 0 0 12px; font-size: 20px; }}
    h3 {{ margin: 16px 0 8px; font-size: 16px; }}
    p {{ margin: 8px 0; }}
    ul {{ padding-left: 22px; margin: 8px 0; }}
    li {{ margin: 6px 0; }}
    a {{ color: var(--accent); }}
    code {{ background: #eef2ef; padding: 2px 5px; border-radius: 4px; }}
    .charts-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(520px, 1fr)); gap: 18px; align-items: start; }}
    .chart-panel {{ align-self: start; }}
    .chart-button {{ display: block; width: 100%; padding: 0; border: 0; background: transparent; cursor: zoom-in; text-align: left; }}
    .chart-image {{ display: block; width: 100%; height: auto; margin-top: 10px; border: 1px solid var(--line); border-radius: 6px; background: #fff; }}
    .chart-note {{ color: var(--muted); font-size: 12px; margin-top: 6px; }}
    .chart-caption {{ color: var(--muted); font-size: 13px; margin-top: 8px; }}
    .references li {{ overflow-wrap: anywhere; }}
    .chart-modal {{ position: fixed; inset: 0; display: none; align-items: center; justify-content: center; background: rgba(15, 23, 42, .86); z-index: 9999; padding: 32px; }}
    .chart-modal.open {{ display: flex; }}
    .chart-modal-inner {{ position: relative; width: min(96vw, 1680px); height: min(92vh, 1000px); overflow: hidden; background: #fff; border-radius: 10px; box-shadow: 0 24px 80px rgba(0,0,0,.34); cursor: grab; }}
    .chart-modal-inner.dragging {{ cursor: grabbing; }}
    .chart-modal img {{ position: absolute; left: 50%; top: 50%; max-width: none; transform: translate(-50%, -50%) scale(1); transform-origin: center center; user-select: none; -webkit-user-drag: none; }}
    .chart-modal-close {{ position: absolute; right: 18px; top: 14px; z-index: 2; border: 0; border-radius: 999px; background: #111827; color: #fff; width: 38px; height: 38px; font-size: 22px; cursor: pointer; }}
    .chart-modal-help {{ position: absolute; left: 18px; bottom: 14px; z-index: 2; color: #fff; background: rgba(17,24,39,.76); border-radius: 999px; padding: 7px 12px; font-size: 13px; }}
  </style>
</head>
<body>
  <header>
    <h1>{escape(title)}</h1>
    <div class="meta">
      <span class="badge">多智能体研究报告</span>
      <span>图表 {chart_count} 个</span>
      <span>参考来源 {citation_count} 条</span>
    </div>
  </header>
  <main>
    {body}
    {chart_blocks}
  </main>
  {_render_chart_modal_script()}
</body>
</html>"""


def _markdown_to_html(markdown: str) -> str:
    lines = markdown.splitlines()
    html: List[str] = []
    in_list = False
    section_open = False
    skip_chart_section = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            html.append("</ul>")
            in_list = False

    def close_section() -> None:
        nonlocal section_open
        close_list()
        if section_open:
            html.append("</section>")
            section_open = False

    for raw in lines:
        line = raw.rstrip()
        if not line:
            close_list()
            continue
        if line.startswith("# "):
            continue
        if line.startswith("## "):
            close_section()
            title = escape(line[3:].strip())
            skip_chart_section = title == "图表"
            if skip_chart_section:
                continue
            klass = "references" if title == "参考来源" else "report-section"
            html.append(f'<section class="{klass}"><h2>{title}</h2>')
            section_open = True
            continue
        if skip_chart_section:
            continue
        if line.startswith("### "):
            close_list()
            html.append(f"<h3>{escape(line[4:].strip())}</h3>")
            continue
        image_match = re.match(r"!\[(.*?)\]\((.*?)\)", line)
        if image_match:
            continue
        if line.startswith("- ") or line.startswith("* "):
            if not in_list:
                html.append("<ul>")
                in_list = True
            html.append(f"<li>{_inline_markdown(line[2:].strip())}</li>")
            continue
        close_list()
        html.append(f"<p>{_inline_markdown(line.strip())}</p>")
    close_section()
    return "\n".join(html)


def _inline_markdown(text: str) -> str:
    escaped = escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    return escaped


def _render_chart_blocks(charts: List[Dict[str, Any]]) -> str:
    if not charts:
        return ""
    blocks = ['<section class="report-section"><h2>图表</h2><div class="charts-grid">']
    for chart in charts:
        chart_id = str(chart.get("chart_id") or "chart")
        title = escape(str(chart.get("title") or chart_id))
        image_src = _chart_image_data_uri(str(chart.get("output_path") or ""))
        if image_src:
            image = (
                f'<button class="chart-button" type="button" data-chart-title="{title}">'
                f'<img class="chart-image" src="{image_src}" alt="{title}">'
                "</button>"
            )
            note = '<div class="chart-note">点击图表可放大；弹窗内支持滚轮缩放、拖拽平移、双击重置。</div>'
        else:
            image = '<p class="chart-note">图表文件不存在，无法显示。</p>'
            note = ""
        blocks.append(
            f'<div class="chart-panel"><h3>{title}</h3>{image}{note}'
            f'<div class="chart-caption">{escape(str(chart.get("source_fields") or ""))}</div></div>'
        )
    blocks.append("</div></section>")
    return "\n".join(blocks)


def _render_chart_modal_script() -> str:
    return """<div class="chart-modal" id="chartModal" aria-hidden="true">
  <button class="chart-modal-close" type="button" aria-label="关闭图表">×</button>
  <div class="chart-modal-inner">
    <img id="chartModalImage" alt="">
  </div>
  <div class="chart-modal-help">滚轮缩放 · 拖拽平移 · 双击重置 · Esc 关闭</div>
</div>
<script>
(() => {
  const modal = document.getElementById('chartModal');
  const inner = modal?.querySelector('.chart-modal-inner');
  const image = document.getElementById('chartModalImage');
  const closeBtn = modal?.querySelector('.chart-modal-close');
  if (!modal || !inner || !image || !closeBtn) return;
  let scale = 1;
  let tx = 0;
  let ty = 0;
  let dragging = false;
  let lastX = 0;
  let lastY = 0;
  function apply() {
    image.style.transform = `translate(calc(-50% + ${tx}px), calc(-50% + ${ty}px)) scale(${scale})`;
  }
  function reset() {
    scale = 1;
    tx = 0;
    ty = 0;
    apply();
  }
  function open(src, title) {
    image.src = src;
    image.alt = title || 'chart';
    reset();
    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
  }
  function close() {
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
    image.removeAttribute('src');
  }
  document.querySelectorAll('.chart-button').forEach((button) => {
    button.addEventListener('click', () => {
      const img = button.querySelector('img');
      if (img && img.src) open(img.src, button.dataset.chartTitle);
    });
  });
  closeBtn.addEventListener('click', close);
  modal.addEventListener('click', (event) => {
    if (event.target === modal) close();
  });
  window.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') close();
  });
  inner.addEventListener('wheel', (event) => {
    event.preventDefault();
    const next = scale * (event.deltaY < 0 ? 1.12 : 0.89);
    scale = Math.min(Math.max(next, 0.6), 6);
    apply();
  }, { passive: false });
  inner.addEventListener('pointerdown', (event) => {
    dragging = true;
    lastX = event.clientX;
    lastY = event.clientY;
    inner.setPointerCapture(event.pointerId);
    inner.classList.add('dragging');
  });
  inner.addEventListener('pointermove', (event) => {
    if (!dragging) return;
    tx += event.clientX - lastX;
    ty += event.clientY - lastY;
    lastX = event.clientX;
    lastY = event.clientY;
    apply();
  });
  inner.addEventListener('pointerup', (event) => {
    dragging = false;
    inner.releasePointerCapture(event.pointerId);
    inner.classList.remove('dragging');
  });
  inner.addEventListener('dblclick', reset);
})();
</script>"""


def _chart_image_data_uri(path_value: str) -> str:
    path = Path(path_value)
    if not path.exists() or not path.is_file():
        return ""
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"
