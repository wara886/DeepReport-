"""Securities research report disclosure blocks — aligned with SAC/CSRC standards."""

from __future__ import annotations

from datetime import date
from html import escape
from typing import Any, Dict, List


DISCLOSURE_HEADER = "## 合规披露与风险提示"

# 中证协标准五档投资评级定义
RATING_DEFINITIONS = {
    "买入":   "预计未来 6 个月内股价涨幅超过基准指数 20% 以上。",
    "增持":   "预计未来 6 个月内股价涨幅超过基准指数 5%~20%。",
    "中性":   "预计未来 6 个月内股价涨跌幅相对基准指数在 ±5% 以内。",
    "减持":   "预计未来 6 个月内股价跌幅超过基准指数 5%~20%。",
    "卖出":   "预计未来 6 个月内股价跌幅超过基准指数 20% 以上。",
    "未评级": "本报告不提供明确投资评级，仅供参考。",
}

ANALYST_DECLARATION = (
    "本报告由 Open DeepReport++ 多智能体系统自动生成，"
    "系统依据公开资料进行分析，不代表任何持牌证券分析师的个人观点。"
    "如用于正式发布，须由具备中国证券业协会注册资质的分析师署名并承担相应责任。"
)


def append_compliance_disclosures(
    markdown: str,
    citations: List[Dict[str, Any]] | None = None,
    rating: str = "未评级",
    report_date: str | None = None,
) -> str:
    citations = citations or []
    report_date = report_date or date.today().isoformat()
    base = _strip_existing_disclosure(markdown).rstrip()
    source_summary = _source_summary(citations)
    rating_def = RATING_DEFINITIONS.get(rating, RATING_DEFINITIONS["未评级"])
    lines = [
        DISCLOSURE_HEADER,
        "",
        "### 一、投资评级说明",
        "",
        f"**本报告投资评级**：{rating}",
        "",
        f"**评级定义**：{rating_def}",
        "",
        "**评级体系**：",
        "| 评级 | 定义 |",
        "|------|------|",
    ]
    for r, d in RATING_DEFINITIONS.items():
        marker = " ◀ 本报告" if r == rating else ""
        lines.append(f"| {r}{marker} | {d} |")
    lines += [
        "",
        "### 二、分析师声明",
        "",
        f"- {ANALYST_DECLARATION}",
        f"- 报告生成日期：{report_date}",
        "- 本报告所引用数据均来自公开渠道，系统已对来源进行结构化标注，具体见参考来源章节。",
        "",
        "### 三、资料来源",
        "",
        f"- {source_summary}",
        "",
        "### 四、风险提示",
        "",
        "- **市场风险**：证券价格受宏观经济、货币政策、市场情绪等多重因素影响，可能大幅波动。",
        "- **行业与经营风险**：行业竞争加剧、技术迭代、管理层变动、重大诉讼等均可能影响公司基本面。",
        "- **数据风险**：本报告所用数据来自第三方公开渠道，存在延迟、错误或不完整的可能，不构成对数据准确性的保证。",
        "- **模型风险**：估值模型基于历史数据和假设参数，实际结果可能与模型预测存在重大偏差。",
        "- **汇率与利率风险**：跨境业务及利率敏感型资产受汇率、利率变动影响。",
        "",
        "### 五、利益冲突与免责声明",
        "",
        "- 本系统未持有所分析证券的任何仓位，亦未与相关公司存在投行或咨询业务关系。",
        "- 本报告不构成买入、卖出或持有任何证券的投资建议，投资者应自行判断并承担投资风险。",
        "- 本报告版权归 Open DeepReport++ 项目所有，未经授权不得用于商业目的。",
        "",
    ]
    return base + "\n\n" + "\n".join(lines)


def append_compliance_disclosures_to_html(
    html: str,
    citations: List[Dict[str, Any]] | None = None,
    rating: str = "未评级",
    report_date: str | None = None,
) -> str:
    citations = citations or []
    report_date = report_date or date.today().isoformat()
    source_summary = escape(_source_summary(citations))
    rating_def = escape(RATING_DEFINITIONS.get(rating, RATING_DEFINITIONS["未评级"]))
    rating_e = escape(rating)
    date_e = escape(report_date)

    rating_rows = ""
    for r, d in RATING_DEFINITIONS.items():
        marker = " ◀ 本报告" if r == rating else ""
        highlight = ' style="background:#eef9f6;font-weight:700;"' if r == rating else ""
        rating_rows += f"<tr{highlight}><td>{escape(r)}{escape(marker)}</td><td>{escape(d)}</td></tr>\n"

    block = f"""<section class="report-section compliance-disclosure">
  <h2>合规披露与风险提示</h2>
  <h3>一、投资评级说明</h3>
  <p><strong>本报告投资评级</strong>：{rating_e}</p>
  <p><strong>评级定义</strong>：{rating_def}</p>
  <table style="border-collapse:collapse;width:100%;font-size:13px;margin:10px 0;">
    <thead><tr style="background:#f5f7f3;"><th style="border:1px solid #d7dfda;padding:6px 10px;text-align:left;">评级</th><th style="border:1px solid #d7dfda;padding:6px 10px;text-align:left;">定义</th></tr></thead>
    <tbody>
{rating_rows}    </tbody>
  </table>
  <h3>二、分析师声明</h3>
  <ul>
    <li>{escape(ANALYST_DECLARATION)}</li>
    <li>报告生成日期：{date_e}</li>
    <li>本报告所引用数据均来自公开渠道，系统已对来源进行结构化标注，具体见参考来源章节。</li>
  </ul>
  <h3>三、资料来源</h3>
  <p>{source_summary}</p>
  <h3>四、风险提示</h3>
  <ul>
    <li><strong>市场风险</strong>：证券价格受宏观经济、货币政策、市场情绪等多重因素影响，可能大幅波动。</li>
    <li><strong>行业与经营风险</strong>：行业竞争加剧、技术迭代、管理层变动、重大诉讼等均可能影响公司基本面。</li>
    <li><strong>数据风险</strong>：本报告所用数据来自第三方公开渠道，存在延迟、错误或不完整的可能，不构成对数据准确性的保证。</li>
    <li><strong>模型风险</strong>：估值模型基于历史数据和假设参数，实际结果可能与模型预测存在重大偏差。</li>
    <li><strong>汇率与利率风险</strong>：跨境业务及利率敏感型资产受汇率、利率变动影响。</li>
  </ul>
  <h3>五、利益冲突与免责声明</h3>
  <ul>
    <li>本系统未持有所分析证券的任何仓位，亦未与相关公司存在投行或咨询业务关系。</li>
    <li>本报告不构成买入、卖出或持有任何证券的投资建议，投资者应自行判断并承担投资风险。</li>
    <li>本报告版权归 Open DeepReport++ 项目所有，未经授权不得用于商业目的。</li>
  </ul>
</section>"""

    html = _strip_existing_html_disclosure(html).rstrip()
    if "</main>" in html:
        return html.replace("</main>", block + "\n  </main>")
    if "</body>" in html:
        return html.replace("</body>", block + "\n</body>")
    return html + "\n" + block + "\n"


def _source_summary(citations: List[Dict[str, Any]]) -> str:
    if not citations:
        return "暂无结构化引用；需人工补充资料来源。"
    counts: Dict[str, int] = {}
    for item in citations:
        authority = str(item.get("source_authority") or item.get("source_type") or "unknown")
        counts[authority] = counts.get(authority, 0) + 1
    parts = [f"{key} {value} 条" for key, value in sorted(counts.items())]
    return "结构化引用共 " + str(len(citations)) + " 条，来源分布：" + "、".join(parts) + "。"


def _strip_existing_disclosure(markdown: str) -> str:
    marker = f"\n{DISCLOSURE_HEADER}"
    if marker in markdown:
        return markdown[: markdown.index(marker)]
    if markdown.startswith(DISCLOSURE_HEADER):
        return ""
    return markdown


def _strip_existing_html_disclosure(html: str) -> str:
    marker = '<section class="report-section compliance-disclosure">'
    index = html.find(marker)
    if index < 0:
        return html
    end = html.find("</section>", index)
    if end < 0:
        return html[:index]
    return html[:index] + html[end + len("</section>"):]
