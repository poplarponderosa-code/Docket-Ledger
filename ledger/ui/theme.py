"""Light and dark, from Docket's palettes. "System" follows the Windows setting."""
from __future__ import annotations

from pathlib import Path

PALETTES: dict[str, dict[str, str]] = {
    "light": dict(name="Light", bg="#E7E5E0", win="#F7F6F3", surface="#FFFFFF", text="#2B2A27", muted="#64615B",
                  border="#E3E0DA", accent="#3F6596", accentSoft="#E6EDF6", hover="#F3F1ED", warn="#B0412A",
                  edited="#FFF4D6", good="#3D7A4F"),
    "dark": dict(name="Dark", bg="#111214", win="#1D1E22", surface="#25272C", text="#E7E5E0", muted="#A5A29C",
                 border="#373A40", accent="#94B5E4", accentSoft="#2C3747", hover="#2C2E34", warn="#F0907A",
                 edited="#4A4126", good="#8CC79B"),
}

current: dict[str, str] = dict(PALETTES["light"])


def system_is_dark() -> bool:
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorScheme"):
            return hints.colorScheme() == Qt.ColorScheme.Dark
    except Exception:      # noqa: BLE001
        pass
    return False


def resolve(choice: str) -> str:
    if choice in ("light", "dark"):
        return choice
    return "dark" if system_is_dark() else "light"


def set_current(name: str) -> dict[str, str]:
    current.clear()
    current.update(PALETTES.get(name, PALETTES["light"]))
    return current


def _check_svg(folder: Path, p: dict[str, str]) -> str:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"check-{p['name'].lower()}.svg"
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">'
        f'<path d="M4 8.3l2.6 2.6L12 5.5" fill="none" stroke="{p["win"]}" stroke-width="2.2" '
        'stroke-linecap="round" stroke-linejoin="round"/></svg>', encoding="utf-8")
    return path.as_posix()


def stylesheet(p: dict[str, str], asset_dir: Path) -> str:
    check = _check_svg(asset_dir, p)
    return f"""
* {{ outline: none; }}
QWidget {{ color: {p['text']}; }}
QMainWindow, #Panel, #TopBar {{ background: {p['win']}; }}
#TopBar {{ border-bottom: 1px solid {p['border']}; }}
#PreviewArea, #PreviewBody {{ background: {p['bg']}; border-radius: 8px; }}
#Section {{ color: {p['muted']}; font-size: 10px; font-weight: 600; padding-top: 8px; }}
#Muted, #Hint {{ color: {p['muted']}; }}
#Hint {{ font-size: 11px; }}
#Warn {{ color: {p['warn']}; font-size: 11px; }}
#WarnBox {{ background: {p['edited']}; border-radius: 6px; padding: 6px 8px; color: {p['text']}; font-size: 11px; }}
#Note {{ color: {p['accent']}; font-size: 11px; font-weight: 600; }}
#Empty {{ color: {p['muted']}; padding: 30px 16px; }}
#Big {{ font-size: 16px; font-weight: 600; }}
#SetupTitle {{ font-size: 18px; font-weight: 600; padding-bottom: 2px; }}
#Card {{ background: {p['win']}; border: 1px solid {p['border']}; border-radius: 10px; }}
#Card[on="true"] {{ border: 2px solid {p['accent']}; background: {p['accentSoft']}; }}
#Status[status="draft"] {{ color: {p['muted']}; font-weight: 600; }}
#Status[status="sent"] {{ color: {p['accent']}; font-weight: 600; }}
#Status[status="paid"] {{ color: {p['good']}; font-weight: 600; }}
#Status[status="overdue"] {{ color: {p['warn']}; font-weight: 600; }}
QToolTip {{ background: {p['text']}; color: {p['win']}; border: 0; padding: 4px 7px; }}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QPlainTextEdit {{
    background: {p['surface']}; color: {p['text']}; border: 1px solid {p['border']}; border-radius: 6px;
    padding: 4px 8px; min-height: 20px;
    selection-background-color: {p['accentSoft']}; selection-color: {p['text']}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus, QPlainTextEdit:focus {{
    border-color: {p['accent']}; }}
QLineEdit:read-only {{ background: {p['win']}; color: {p['muted']}; }}
QComboBox::drop-down, QDateEdit::drop-down {{ border: 0; width: 18px; }}
QComboBox QAbstractItemView {{ background: {p['surface']}; color: {p['text']}; border: 1px solid {p['border']};
    selection-background-color: {p['accentSoft']}; selection-color: {p['text']}; outline: 0; }}

QPushButton, QToolButton {{ background: {p['surface']}; color: {p['text']}; border: 1px solid {p['border']};
    border-radius: 6px; padding: 5px 10px; }}
QPushButton:hover, QToolButton:hover {{ background: {p['hover']}; }}
QPushButton:disabled, QToolButton:disabled {{ color: {p['muted']}; }}
QPushButton[primary="true"] {{ background: {p['accent']}; color: {p['win']}; border-color: {p['accent']};
    font-weight: 600; padding: 7px 16px; }}
QPushButton[primary="true"]:disabled {{ background: {p['border']}; border-color: {p['border']}; color: {p['muted']}; }}
QPushButton[seg="true"] {{ border-radius: 0; padding: 6px 16px; font-weight: 600; color: {p['muted']}; }}
QPushButton[seg="true"]:checked {{ background: {p['accentSoft']}; color: {p['accent']}; border-color: {p['accent']}; }}
QPushButton[segpos="first"] {{ border-top-left-radius: 7px; border-bottom-left-radius: 7px; }}
QPushButton[segpos="last"] {{ border-top-right-radius: 7px; border-bottom-right-radius: 7px; }}
QPushButton[link="true"] {{ background: transparent; border: 0; color: {p['accent']}; padding: 0; text-align: left; }}
QPushButton[swatch="true"] {{ border-radius: 6px; padding: 0; min-width: 26px; min-height: 22px; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QToolButton[flat="true"] {{ border: 0; background: transparent; font-size: 15px; padding: 3px 6px; }}
QToolButton[flat="true"]:hover {{ background: {p['hover']}; }}

QCheckBox, QRadioButton {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 13px; height: 13px; border-radius: 3px; border: 1px solid {p['muted']};
    background: {p['surface']}; }}
QCheckBox::indicator:hover {{ border-color: {p['accent']}; }}
QCheckBox::indicator:checked {{ background: {p['accent']}; border-color: {p['accent']}; image: url("{check}"); }}

QListWidget {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 8px; padding: 2px; }}
QListWidget::item {{ padding: 6px 6px; border-radius: 5px; }}
QListWidget::item:selected {{ background: {p['accentSoft']}; color: {p['text']}; }}
QListWidget::item:hover:!selected {{ background: {p['hover']}; }}
QListWidget::indicator {{ width: 13px; height: 13px; border-radius: 3px; border: 1px solid {p['muted']};
    background: {p['surface']}; }}
QListWidget::indicator:checked {{ background: {p['accent']}; border-color: {p['accent']}; image: url("{check}"); }}

QTableWidget {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 8px;
    gridline-color: {p['border']}; selection-background-color: {p['accentSoft']}; selection-color: {p['text']}; }}
QTableWidget::indicator {{ width: 13px; height: 13px; border-radius: 3px; border: 1px solid {p['muted']};
    background: {p['surface']}; }}
QTableWidget::indicator:checked {{ background: {p['accent']}; border-color: {p['accent']}; image: url("{check}"); }}
QHeaderView::section {{ background: {p['win']}; color: {p['muted']}; border: 0; border-bottom: 1px solid {p['border']};
    padding: 5px 6px; font-size: 11px; font-weight: 600; }}
QTableCornerButton::section {{ background: {p['win']}; border: 0; }}

QScrollArea {{ border: 0; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p['border']}; border-radius: 3px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: {p['muted']}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {p['border']}; border-radius: 3px; min-width: 28px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QSplitter::handle {{ background: {p['win']}; }}
QTabWidget::pane {{ border: 1px solid {p['border']}; border-radius: 8px; background: {p['surface']}; top: -1px; }}
QTabBar::tab {{ background: transparent; color: {p['muted']}; padding: 6px 12px; border: 1px solid transparent;
    border-top-left-radius: 7px; border-top-right-radius: 7px; }}
QTabBar::tab:selected {{ background: {p['surface']}; color: {p['text']}; border-color: {p['border']};
    border-bottom-color: {p['surface']}; font-weight: 600; }}
QMenu {{ background: {p['surface']}; color: {p['text']}; border: 1px solid {p['border']}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background: {p['accentSoft']}; }}
QMenu::separator {{ height: 1px; background: {p['border']}; margin: 4px 6px; }}
QDialog {{ background: {p['surface']}; }}
QSlider::groove:horizontal {{ height: 4px; background: {p['border']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {p['accent']}; width: 14px; margin: -6px 0; border-radius: 7px; }}
QStatusBar {{ background: {p['win']}; color: {p['muted']}; }}
QProgressDialog {{ background: {p['surface']}; }}
"""
