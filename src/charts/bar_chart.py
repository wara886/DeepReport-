"""Bar chart rendering using PIL."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont


def render_bar_chart(
    bars: Sequence[Tuple[str, float]],
    output_path: str | Path,
    title: str = "Bar Chart",
    width: int = 1400,
    height: int | None = None,
) -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    height = height or max(560, 130 + len(bars) * 58)

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()

    margin_left = 330
    margin_right = 110
    margin_top = 72
    margin_bottom = 52
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
    slot_h = plot_h / n
    bar_h = max(16, int(slot_h * 0.48))

    for idx, (label, value) in enumerate(bars):
        y_center = margin_top + int((idx + 0.5) * slot_h)
        w = int((float(value) / max_v) * plot_w)
        x0 = margin_left
        y0 = y_center - bar_h // 2
        x1 = margin_left + w
        y1 = y_center + bar_h // 2
        draw.rectangle((x0, y0, x1, y1), fill="#ff7f0e", outline="#cc6500")
        draw.text((28, y_center - 6), _short_label(str(label), limit=42), fill="black", font=font)
        draw.text((min(x1 + 10, width - margin_right + 8), y_center - 6), f"{float(value):.2f}", fill="#4b5563", font=font)

    img.save(out)
    return out


def _short_label(label: str, limit: int = 42) -> str:
    if len(label) <= limit:
        return label
    return label[: max(limit - 3, 1)] + "..."
