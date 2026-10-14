"""Colors pulled from album artwork for the Now Playing background.

The two returned colors are darkened so white text stays readable. They are
display colors, not audio data.
"""

from __future__ import annotations

import colorsys
import zlib

from PIL import Image, UnidentifiedImageError


def _score(rgb: tuple[int, int, int]) -> float:
    red, green, blue = (channel / 255 for channel in rgb)
    peak = max(red, green, blue)
    floor = min(red, green, blue)
    saturation = 0 if peak == 0 else (peak - floor) / peak
    # Colorful mid tones make a better glow than near-black or near-white.
    mid_bonus = 0.35 if 0.22 < peak < 0.9 else 0
    return saturation * 2.2 + mid_bonus + peak * 0.15


def _dark(rgb: tuple[int, int, int], amount: float) -> tuple[float, float, float, float]:
    return (rgb[0] / 255 * amount, rgb[1] / 255 * amount, rgb[2] / 255 * amount, 1)


def _vivid(rgb: tuple[int, int, int]) -> tuple[float, float, float, float]:
    red, green, blue = (channel / 255 for channel in rgb)
    hue, _sat, val = colorsys.rgb_to_hsv(red, green, blue)
    sat = min(1.0, max(0.45, _score(rgb)))
    val = min(1.0, max(0.55, val))
    rr, gg, bb = colorsys.hsv_to_rgb(hue, min(0.85, sat), val)
    return (rr, gg, bb, 1)


def palette_from_image(path: str) -> tuple[tuple, tuple, tuple] | None:
    """Return (glow, background_a, background_b) or None when the file is unusable."""
    try:
        image = Image.open(path).convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError):
        return None
    small = image.resize((18, 18))
    counted = small.getcolors(18 * 18) or []
    if not counted:
        return None
    ranked = sorted(counted, key=lambda item: _score(item[1]), reverse=True)
    primary = ranked[0][1]
    secondary = primary
    for _count, rgb in ranked[1:]:
        distance = sum(abs(a - b) for a, b in zip(rgb, primary))
        if distance > 70:
            secondary = rgb
            break
    return (_vivid(primary), _dark(primary, 0.28), _dark(secondary, 0.16))


def palette_from_text(text: str) -> tuple[tuple, tuple, tuple]:
    """Stable accent for tracks that have no embedded artwork."""
    hue = (zlib.crc32((text or "vibewave").encode("utf-8")) % 360) / 360
    vivid = colorsys.hsv_to_rgb(hue, 0.62, 0.95)
    deep = colorsys.hsv_to_rgb(hue, 0.55, 0.28)
    deep2 = colorsys.hsv_to_rgb((hue + 0.08) % 1, 0.45, 0.14)
    return (
        (vivid[0], vivid[1], vivid[2], 1),
        (deep[0], deep[1], deep[2], 1),
        (deep2[0], deep2[1], deep2[2], 1),
    )
