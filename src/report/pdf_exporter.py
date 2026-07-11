"""Polished PDF export for formal financial research packages."""

from __future__ import annotations

from html import escape
from pathlib import Path
import re
from typing import Any, Dict, List


def export_markdown_to_pdf(
    markdown: str,
    output_path: str | Path,
    *,
    title: str = "FinSight 金融研究报告",
    metadata: Dict[str, Any] | None = None,
) -> Path:
    """Render Markdown into an A4 PDF with Chinese typography and page numbers."""

    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import (
        BaseDocTemplate,
        Frame,
        PageBreak,
        PageTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
    )

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    font_name = "STSong-Light"
    try:
        pdfmetrics.registerFont(UnicodeCIDFont(font_name))
    except KeyError:
        pass

    styles = getSampleStyleSheet()
    body = ParagraphStyle(
        "FinSightBody",
        parent=styles["BodyText"],
        fontName=font_name,
        fontSize=9.5,
        leading=16,
        textColor=colors.HexColor("#283747"),
        spaceAfter=5,
    )
    title_style = ParagraphStyle(
        "FinSightTitle",
        parent=body,
        fontSize=22,
        leading=30,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#17365D"),
        spaceAfter=12,
    )
    heading_styles = {
        1: ParagraphStyle("H1", parent=body, fontSize=16, leading=22, textColor=colors.HexColor("#17365D"), spaceBefore=12, spaceAfter=8),
        2: ParagraphStyle("H2", parent=body, fontSize=13, leading=19, textColor=colors.HexColor("#24527A"), spaceBefore=10, spaceAfter=6),
        3: ParagraphStyle("H3", parent=body, fontSize=11, leading=17, textColor=colors.HexColor("#376A92"), spaceBefore=8, spaceAfter=4),
    }
    bullet_style = ParagraphStyle("Bullet", parent=body, leftIndent=13, firstLineIndent=-8, bulletIndent=3)
    small = ParagraphStyle("Small", parent=body, fontSize=8, leading=12, textColor=colors.HexColor("#5D6D7E"))

    doc = BaseDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=19 * mm,
        rightMargin=19 * mm,
        topMargin=20 * mm,
        bottomMargin=18 * mm,
        title=title,
        author="FinSight AI",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")

    def draw_page(canvas: Any, document: Any) -> None:
        canvas.saveState()
        canvas.setFont(font_name, 7.5)
        canvas.setFillColor(colors.HexColor("#6C7A89"))
        canvas.drawString(doc.leftMargin, 10 * mm, "FinSight AI · 仅供研究参考，不构成投资建议")
        canvas.drawRightString(A4[0] - doc.rightMargin, 10 * mm, f"第 {document.page} 页")
        canvas.setStrokeColor(colors.HexColor("#D5D8DC"))
        canvas.line(doc.leftMargin, 14 * mm, A4[0] - doc.rightMargin, 14 * mm)
        canvas.restoreState()

    doc.addPageTemplates([PageTemplate(id="report", frames=[frame], onPage=draw_page)])
    story: List[Any] = [Paragraph(escape(title), title_style)]
    meta = metadata or {}
    if meta:
        rows = [[Paragraph(escape(str(key)), small), Paragraph(escape(str(value)), small)] for key, value in meta.items()]
        table = Table(rows, colWidths=[35 * mm, doc.width - 35 * mm], hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EEF3F7")),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CCD6DD")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story.extend([table, Spacer(1, 7 * mm)])

    for block in _markdown_blocks(markdown):
        kind = block["kind"]
        text = escape(block["text"])
        if kind == "heading":
            level = min(int(block["level"]), 3)
            story.append(Paragraph(text, heading_styles[level]))
        elif kind == "bullet":
            story.append(Paragraph(f"• {text}", bullet_style))
        elif kind == "numbered":
            story.append(Paragraph(text, bullet_style))
        elif kind == "page_break":
            story.append(PageBreak())
        else:
            story.append(Paragraph(text or " ", body))
    doc.build(story)
    return path


def _markdown_blocks(markdown: str) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []
    for raw in str(markdown or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("```"):
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            blocks.append({"kind": "heading", "level": len(heading.group(1)), "text": _inline(heading.group(2))})
            continue
        bullet = re.match(r"^[-*]\s+(.*)$", line)
        if bullet:
            blocks.append({"kind": "bullet", "text": _inline(bullet.group(1))})
            continue
        numbered = re.match(r"^(\d+\.)\s+(.*)$", line)
        if numbered:
            blocks.append({"kind": "numbered", "text": f"{numbered.group(1)} {_inline(numbered.group(2))}"})
            continue
        if line in {"---", "***"}:
            blocks.append({"kind": "page_break", "text": ""})
            continue
        if line.startswith("|") and line.endswith("|"):
            blocks.append({"kind": "paragraph", "text": " ｜ ".join(part.strip() for part in line.strip("|").split("|") if part.strip(" -"))})
            continue
        blocks.append({"kind": "paragraph", "text": _inline(line)})
    return blocks


def _inline(text: str) -> str:
    value = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"图表：\1", text)
    value = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1（\2）", value)
    return re.sub(r"[*_`]+", "", value).strip()
