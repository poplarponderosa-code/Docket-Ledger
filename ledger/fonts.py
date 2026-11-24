"""Fonts for the PDF. Windows fonts are embedded, so the PDF looks the same anywhere."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from reportlab.lib.fonts import addMapping
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# Built into every PDF reader (not embedded).
BUILTIN = {
    "Helvetica": ("Helvetica", "Helvetica-Bold"),
    "Times": ("Times-Roman", "Times-Bold"),
    "Courier": ("Courier", "Courier-Bold"),
}

# family -> (regular file, bold file), looked for in the Windows fonts folder.
WINDOWS = {
    "Calibri": ("calibri.ttf", "calibrib.ttf"),
    "Arial": ("arial.ttf", "arialbd.ttf"),
    "Segoe UI": ("segoeui.ttf", "segoeuib.ttf"),
    "Aptos": ("aptos.ttf", "aptos-bold.ttf"),
    "Verdana": ("verdana.ttf", "verdanab.ttf"),
    "Tahoma": ("tahoma.ttf", "tahomabd.ttf"),
    "Trebuchet MS": ("trebuc.ttf", "trebucbd.ttf"),
    "Georgia": ("georgia.ttf", "georgiab.ttf"),
    "Times New Roman": ("times.ttf", "timesbd.ttf"),
    "Garamond": ("gara.ttf", "garabd.ttf"),
    "Consolas": ("consola.ttf", "consolab.ttf"),
}

# Used when building on Linux (tests); same idea, different files.
OTHER = {
    "Carlito": ("Carlito-Regular.ttf", "Carlito-Bold.ttf"),
    "Liberation Sans": ("LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf"),
    "DejaVu Sans": ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"),
}

PREFERRED_DEFAULT = ("Calibri", "Aptos", "Segoe UI", "Arial", "Carlito", "Liberation Sans")

_available: dict[str, tuple[Path, Path]] | None = None
_registered: set[str] = set()


def _font_dirs() -> list[Path]:
    dirs = []
    if sys.platform == "win32":
        windir = os.environ.get("WINDIR", r"C:\Windows")
        dirs.append(Path(windir) / "Fonts")
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    else:
        for base in ("/usr/share/fonts", "/usr/local/share/fonts", str(Path.home() / ".fonts")):
            if Path(base).is_dir():
                dirs.extend(p for p in Path(base).rglob("*") if p.is_dir())
                dirs.append(Path(base))
    return dirs


def _find(name: str, dirs: list[Path]) -> Path | None:
    for d in dirs:
        p = d / name
        if p.exists():
            return p
        # Windows font folders are case-insensitive; elsewhere check both cases.
        alt = d / name.lower()
        if alt.exists():
            return alt
    return None


def available() -> dict[str, tuple[Path, Path]]:
    """Installed font families this app knows how to embed."""
    global _available
    if _available is None:
        dirs = _font_dirs()
        _available = {}
        table = WINDOWS if sys.platform == "win32" else {**WINDOWS, **OTHER}
        for family, (reg, bold) in table.items():
            r, b = _find(reg, dirs), _find(bold, dirs)
            if r:
                _available[family] = (r, b or r)
    return _available


def families() -> list[str]:
    return list(available()) + list(BUILTIN)


def default_family() -> str:
    for f in PREFERRED_DEFAULT:
        if f in available():
            return f
    return "Helvetica"


def resolve(family: str) -> tuple[str, str]:
    """(regular, bold) ReportLab font names for a family, registering it if needed.
    Unknown or missing fonts fall back to the default, then Helvetica."""
    family = family or default_family()
    if family in BUILTIN:
        return BUILTIN[family]
    files = available().get(family)
    if not files:
        if family != default_family():
            return resolve(default_family())
        return BUILTIN["Helvetica"]
    reg_name, bold_name = f"DC-{family}", f"DC-{family}-Bold"
    if family not in _registered:
        try:
            pdfmetrics.registerFont(TTFont(reg_name, str(files[0])))
            pdfmetrics.registerFont(TTFont(bold_name, str(files[1])))
        except Exception:      # noqa: BLE001 - a broken font file falls back quietly
            return BUILTIN["Helvetica"]
        addMapping(reg_name, 0, 0, reg_name)
        addMapping(reg_name, 1, 0, bold_name)
        addMapping(reg_name, 0, 1, reg_name)
        addMapping(reg_name, 1, 1, bold_name)
        _registered.add(family)
    return reg_name, bold_name
