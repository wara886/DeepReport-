"""Securities research report disclosure blocks."""

from __future__ import annotations

from html import escape
from typing import Any, Dict, List


DISCLOSURE_HEADER = "## 合规披露与风险提示"


def append_compliance_disclosures(
    markdown: str,
    citations: List[Dict[str, Any]] | None = None,
    rating_definition: str = "未评级",
) -> str:
    """Append a compact compliance/disclosure section to Markdown reports."""

    citations = citations or []
    base = _strip_existing_disclosure(markdown).rstrip()
    source_summary = _source_summary(citations)
    lines = [
        DISCLOSURE_HEADER,
        "",
        f"- **投资评级**：{rating_definition}。本报告不构成买入、卖出或持有任何证券的直接建议。",
        f"- **资料来源**：{source_summary}",
        "- **风险提示**：市场波动、宏观政策变化、行业竞争、公司经营、汇率与利率变化、数据延迟或第三方数据错误均可能影响结论。",
        "- **利益冲突声明**：本系统未接入作者持仓、投行业务或客户交易信息；如用于正式发布，应由持牌机构补充人工复核和利益冲突披露。",
        "- **使用限制**：本报告由多智能体系统基于可用公开资料和本地数据自动生成，仅供研究和技术验证参考。",
        "",
    ]
    return base + "\n\n" + "\n".join(lines)


def append_compliance_disclosures_to_html(
    html: str,
    citations: List[Dict[str, Any]] | None = None,
    rating_definition: str = "未评级",
) -> str:
    citations = citations or []
    source_summary = escape(_source_summary(citations))
    rating = escape(rating_definition)
    block = f"""
<section class="report-section compliance-disclosure">
  <h2>合规披露与风险提示</h2>
  <ul>
    <li><strong>投资评级</strong>：{rating}。本报告不构成买入、卖出或持有任何证券的直接建议。</li>
    <li><strong>资料来源</strong>：{source_summary}</li>
    <li><strong>风险提示</strong>：市场波动、宏观政策变化、行业竞争、公司经营、汇率与利率变化、数据延迟或第三方数据错误均可能影响结论。</li>
    <li><strong>利益冲突声明</strong>：本系统未接入作者持仓、投行业务或客户交易信息；如用于正式发布，应由持牌机构补充人工复核和利益冲突披露。</li>
    <li><strong>使用限制</strong>：本报告由多智能体系统基于可用公开资料和本地数据自动生成，仅供研究和技术验证参考。</li>
  </ul>
</section>
""".strip()
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
    return html[:index] + html[end + len("</section>") :]
