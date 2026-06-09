"""Font auto-detection for Chinese/CJK text rendering in charts.

Searches for a system-installed CJK TrueType font (macOS, Linux) and
falls back to PIL's built-in default font (which may not support CJK
on older Pillow versions like 9.x).
"""

from __future__ import annotations

from pathlib import Path
from PIL import ImageFont

# Platform-specific CJK font candidates, checked in order.
_CJK_FONT_CANDIDATES = [
    # macOS system fonts
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    # Linux — fonts-noto-cjk (Debian/Ubuntu)
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    # Linux — fonts-wqy-zenhei (Debian/Ubuntu)
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    # Linux — DroidSansFallback (older Debian)
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
]

_font_cache: dict[int, ImageFont.ImageFont] = {}
_cjk_font_path: str | None = None
_checked: bool = False


def _find_cjk_font() -> str | None:
    """Return the path of the first available CJK TrueType font, or None."""
    global _cjk_font_path, _checked
    if _checked:
        return _cjk_font_path
    _checked = True
    for candidate in _CJK_FONT_CANDIDATES:
        if Path(candidate).is_file():
            _cjk_font_path = candidate
            return candidate
    return None


def get_chinese_font(size: int = 14) -> ImageFont.ImageFont:
    """Return a font capable of rendering Chinese/CJK characters.

    When a CJK TrueType font is found on the system it is loaded at the
    requested *size* (points).  Otherwise PIL's built-in default font is
    returned (which on Pillow < 10 has only Latin-1 glyphs and will fail
    when asked to render CJK text).
    """
    if size in _font_cache:
        return _font_cache[size]

    path = _find_cjk_font()
    if path:
        font = ImageFont.truetype(path, size)
    else:
        font = ImageFont.load_default()

    _font_cache[size] = font
    return font
