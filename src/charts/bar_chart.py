"""Bar chart rendering using PIL."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont


def render_bar_chart(
    bars: Sequence[Tuple[str, float]],
    output_path: str | Path,
    title: str = "Bar Chart",
    width: int = 900,
    height: int = 520,
) -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()

    margin_left = 80
    margin_right = 40
    margin_top = 60
    margin_bottom = 90
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom

    draw.line([(margin_left, margin_top), (margin_left, margin_top + plot_h)], fill="black", width=2)
    draw.line(
        [(margin_left, margin_top + plot_h), (margin_left + plot_w, margin_top + plot_h)],
        fill="black",
        width=2,
    )
    draw.text((margin_left, 20), title, fill="black", font=font)

    if not bars:
        draw.text((margin_left + 20, margin_top + 20), "No data", fill="gray", font=font)
        img.save(out)
        return out

    values = [float(v) for _, v in bars]
    max_v = max(max(values), 1e-6)
    n = len(bars)
    slot_w = plot_w / n
    bar_w = int(slot_w * 0.55)

    for idx, (label, value) in enumerate(bars):
        x_center = margin_left + int((idx + 0.5) * slot_w)
        h = int((float(value) / max_v) * plot_h)
        x0 = x_center - bar_w // 2
        y0 = margin_top + plot_h - h
        x1 = x_center + bar_w // 2
        y1 = margin_top + plot_h
        draw.rectangle((x0, y0, x1, y1), fill="#ff7f0e", outline="#cc6500")
        draw.text((x_center - 18, margin_top + plot_h + 10), str(label), fill="gray", font=font)
        draw.text((x_center - 16, y0 - 16), f"{float(value):.2f}", fill="gray", font=font)

    img.save(out)
    return out

