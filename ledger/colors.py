"""Colours: the main colours of a logo, and readable text on a coloured header. No Qt in here."""
from __future__ import annotations

import colorsys
from pathlib import Path

DEFAULT_ACCENT = "#3F4A5A"
DARK_TEXT = "#1F2328"
LIGHT_TEXT = "#FFFFFF"


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def _rgb(hexstr: str) -> tuple[int, int, int]:
    h = hexstr.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def logo_colors(path: Path | None, count: int = 4) -> list[str]:
    """The logo's most common real colours: transparent, near-white, near-black and grey pixels skipped."""
    if path is None:
        return []
    try:
        from PIL import Image
        img = Image.open(path).convert("RGBA")
    except Exception:      # noqa: BLE001
        return []
    img.thumbnail((160, 160))
    buckets: dict[tuple[int, int, int], list[int]] = {}
    raw = img.tobytes()
    for i in range(0, len(raw), 4):
        r, g, b, a = raw[i], raw[i + 1], raw[i + 2], raw[i + 3]
        if a < 128:
            continue
        h, lum, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        if lum > 0.93 or lum < 0.07 or s < 0.18:
            continue
        key = (r >> 4, g >> 4, b >> 4)
        acc = buckets.setdefault(key, [0, 0, 0, 0])
        acc[0] += r
        acc[1] += g
        acc[2] += b
        acc[3] += 1
    ranked = sorted(buckets.values(), key=lambda v: v[3], reverse=True)
    out: list[str] = []
    for r, g, b, n in ranked:
        rgb = (r // n, g // n, b // n)
        # skip colours too close to one already picked
        if any(sum(abs(x - y) for x, y in zip(rgb, _rgb(o))) < 60 for o in out):
            continue
        out.append(_hex(rgb))
        if len(out) >= count:
            break
    return out


def luminance(hexstr: str) -> float:
    def ch(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = _rgb(hexstr)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def text_on(bg: str, choice: str = "auto") -> str:
    """Header text colour: light or dark, whichever reads better (unless chosen)."""
    if choice == "light":
        return LIGHT_TEXT
    if choice == "dark":
        return DARK_TEXT
    return LIGHT_TEXT if contrast(bg, LIGHT_TEXT) >= contrast(bg, DARK_TEXT) else DARK_TEXT


def resolve_accent(accent: str, logo: Path | None) -> str:
    if accent:
        return accent
    found = logo_colors(logo, 1)
    return found[0] if found else DEFAULT_ACCENT
