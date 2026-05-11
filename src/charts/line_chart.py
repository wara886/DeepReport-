"""Line chart rendering using PIL."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont


def render_line_chart(
    points: Sequence[Tuple[str, float]],
    output_path: str | Path,
    title: str = "Line Chart",
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

    # Axes
    draw.line([(margin_left, margin_top), (margin_left, margin_top + plot_h)], fill="black", width=2)
    draw.line(
        [(margin_left, margin_top + plot_h), (margin_left + plot_w, margin_top + plot_h)],
        fill="black",
        width=2,
    )
    draw.text((margin_left, 20), title, fill="black", font=font)

    if not points:
        draw.text((margin_left + 20, margin_top + 20), "No data", fill="gray", font=font)
        img.save(out)
        return out

    values = [float(v) for _, v in points]
    min_v = min(values)
    max_v = max(values)
    span = max(max_v - min_v, 1e-6)

    # Y tick labels
    for i in range(5):
        frac = i / 4
        y = margin_top + int(plot_h - frac * plot_h)
        tick_val = min_v + frac * span
        draw.line([(margin_left - 5, y), (margin_left, y)], fill="black", width=1)
        draw.text((10, y - 6), f"{tick_val:.2f}", fill="gray", font=font)

    n = len(points)
    coords: List[Tuple[int, int]] = []
    for idx, (label, value) in enumerate(points):
        x = margin_left + int((idx / (n - 1 if n > 1 else 1)) * plot_w)
        y_norm = (float(value) - min_v) / span
        y = margin_top + int(plot_h - y_norm * plot_h)
        coords.append((x, y))
        draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill="#1f77b4", outline="#1f77b4")
        draw.text((x - 18, margin_top + plot_h + 10), str(label), fill="gray", font=font)

    if len(coords) >= 2:
        draw.line(coords, fill="#1f77b4", width=3)

    img.save(out)
    return out

