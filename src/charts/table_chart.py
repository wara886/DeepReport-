"""Table chart rendering using PIL."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont


def render_table_chart(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    output_path: str | Path,
    title: str = "Table",
    width: int = 960,
    row_height: int = 34,
) -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    n_rows = len(rows) + 1
    height = 90 + n_rows * row_height + 20

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()

    margin_left = 40
    margin_top = 50
    table_w = width - 2 * margin_left
    n_cols = max(len(headers), 1)
    col_w = table_w // n_cols

    draw.text((margin_left, 18), title, fill="black", font=font)

    # Header background
    draw.rectangle(
        (margin_left, margin_top, margin_left + table_w, margin_top + row_height),
        fill="#f2f2f2",
        outline="black",
        width=1,
    )

    for c, text in enumerate(headers):
        x = margin_left + c * col_w + 8
        draw.text((x, margin_top + 10), str(text), fill="black", font=font)

    for r, row in enumerate(rows):
        y0 = margin_top + (r + 1) * row_height
        y1 = y0 + row_height
        fill = "#ffffff" if r % 2 == 0 else "#fafafa"
        draw.rectangle((margin_left, y0, margin_left + table_w, y1), fill=fill, outline="black", width=1)
        for c in range(n_cols):
            text = str(row[c]) if c < len(row) else ""
            x = margin_left + c * col_w + 8
            draw.text((x, y0 + 10), text, fill="black", font=font)

    # Column separators
    for c in range(1, n_cols):
        x = margin_left + c * col_w
        draw.line((x, margin_top, x, margin_top + n_rows * row_height), fill="black", width=1)

    img.save(out)
    return out

