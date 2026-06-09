"""Bar chart rendering using PIL."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Tuple

from PIL import Image, ImageDraw

from .fonts import get_chinese_font


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
    font = get_chinese_font(14)

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
    min_v = min(min(values), 0.0)
    max_v = max(max(values), 0.0)
    span = max(max_v - min_v, 1e-6)
    baseline_y = margin_top + int((max_v / span) * plot_h)
    baseline_y = max(margin_top, min(margin_top + plot_h, baseline_y))
    draw.line([(margin_left, baseline_y), (margin_left + plot_w, baseline_y)], fill="#777777", width=1)
    n = len(bars)
    slot_w = plot_w / n
    bar_w = int(slot_w * 0.55)

    for idx, (label, value) in enumerate(bars):
        x_center = margin_left + int((idx + 0.5) * slot_w)
        value = float(value)
        value_y = margin_top + int(((max_v - value) / span) * plot_h)
        value_y = max(margin_top, min(margin_top + plot_h, value_y))
        x0 = x_center - bar_w // 2
        y0 = min(value_y, baseline_y)
        x1 = x_center + bar_w // 2
        y1 = max(value_y, baseline_y)
        if y0 == y1:
            y0 = max(margin_top, y0 - 1)
        draw.rectangle((x0, y0, x1, y1), fill="#ff7f0e", outline="#cc6500")
        draw.text((x_center - 18, margin_top + plot_h + 10), str(label), fill="gray", font=font)
        value_label_y = y0 - 16 if value >= 0 else y1 + 4
        value_label_y = max(margin_top, min(margin_top + plot_h + 20, value_label_y))
        draw.text((x_center - 16, value_label_y), f"{value:.2f}", fill="gray", font=font)

    img.save(out)
    return out

