"""Page layout: pick a starting layout, then drag blocks onto a small page. They snap into place."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from ..store import ELEMENTS, PRESETS, SLOTS, normalise_layout
from . import theme
from .widgets import hint

SLOT_NAMES = {"top-left": "Top left", "top-center": "Top centre", "top-right": "Top right",
              "info-left": "Below, left", "info-right": "Below, right"}


class PageCanvas(QWidget):
    """A small page with five drop zones. Drag a block to a zone; it snaps there."""
    changed = Signal(dict)

    def __init__(self, layout: dict, show_invoice: bool = True, parent: QWidget | None = None):
        super().__init__(parent)
        self.layout_map = normalise_layout(layout)
        self.show_invoice = show_invoice
        self.setMinimumSize(300, 330)
        self.setMouseTracking(True)
        self._drag: str | None = None
        self._drag_pos = QPointF()
        self._hover_slot: str | None = None

    def set_layout(self, layout: dict) -> None:
        self.layout_map = normalise_layout(layout)
        self.update()

    # ---- geometry
    def _page(self) -> QRectF:
        h = self.height() - 10
        w = min(self.width() - 10, h * 8.5 / 11)
        h = w * 11 / 8.5
        return QRectF((self.width() - w) / 2, 5, w, h)

    def _zones(self) -> dict[str, QRectF]:
        pg = self._page()
        m = pg.width() * 0.07
        inner = pg.adjusted(m, m, -m, -m)
        top_h = inner.height() * 0.2
        third = inner.width() / 3
        info_y = inner.top() + top_h + inner.height() * 0.13
        half = inner.width() / 2
        return {
            "top-left": QRectF(inner.left(), inner.top(), third - 3, top_h),
            "top-center": QRectF(inner.left() + third, inner.top(), third - 3, top_h),
            "top-right": QRectF(inner.left() + 2 * third, inner.top(), third, top_h),
            "info-left": QRectF(inner.left(), info_y, half - 3, top_h),
            "info-right": QRectF(inner.left() + half, info_y, half, top_h),
        }

    def _elements(self) -> list[str]:
        return [e for e in ELEMENTS if self.show_invoice or e in ("logo", "sender", "billto", "details")]

    def _chip_rects(self) -> dict[str, QRectF]:
        zones = self._zones()
        out: dict[str, QRectF] = {}
        by_slot: dict[str, list[str]] = {}
        for e in self._elements():
            by_slot.setdefault(self.layout_map[e], []).append(e)
        for slot, els in by_slot.items():
            z = zones[slot].adjusted(4, 4, -4, -4)
            ch = min(24.0, (z.height() - 4 * (len(els) - 1)) / len(els))
            for i, e in enumerate(els):
                out[e] = QRectF(z.left(), z.top() + i * (ch + 4), z.width(), ch)
        return out

    # ---- painting
    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = theme.current
        pg = self._page()
        p.setPen(QPen(QColor(pal["border"]), 1))
        p.setBrush(QColor("#FFFFFF"))
        p.drawRoundedRect(pg, 4, 4)
        zones = self._zones()
        # rule under the top row, the title and some table lines, so it reads as a page
        m = pg.width() * 0.07
        rule_y = zones["top-left"].bottom() + pg.height() * 0.03
        p.setPen(QPen(QColor("#9AA3AE"), 1.4))
        p.drawLine(QPointF(pg.left() + m, rule_y), QPointF(pg.right() - m, rule_y))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#C9CED6"))
        p.drawRoundedRect(QRectF(pg.left() + m, rule_y + pg.height() * 0.025, pg.width() * 0.3, 6), 3, 3)
        ty = zones["info-left"].bottom() + pg.height() * 0.05
        p.setBrush(QColor("#7D8794"))
        p.drawRect(QRectF(pg.left() + m, ty, pg.width() - 2 * m, 9))
        p.setBrush(QColor("#E3E6EA"))
        for i in range(6):
            p.drawRect(QRectF(pg.left() + m, ty + 14 + i * 11, pg.width() - 2 * m, 5))
        # zones
        font = QFont(self.font())
        font.setPointSizeF(max(7.0, font.pointSizeF() - 1.5))
        p.setFont(font)
        for slot, z in zones.items():
            active = self._drag is not None and slot == self._hover_slot
            p.setPen(QPen(QColor(pal["accent"] if active else "#C5CBD3"), 1.5 if active else 1, Qt.PenStyle.DashLine))
            p.setBrush(QColor(pal["accentSoft"]) if active else Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(z, 5, 5)
        # chips
        for e, r in self._chip_rects().items():
            if e == self._drag:
                continue
            self._draw_chip(p, e, r, pal)
        if self._drag is not None:
            r = QRectF(0, 0, 110, 24)
            r.moveCenter(self._drag_pos)
            self._draw_chip(p, self._drag, r, pal, lifted=True)
        p.end()

    def _draw_chip(self, p: QPainter, e: str, r: QRectF, pal: dict, lifted: bool = False) -> None:
        p.setPen(QPen(QColor(pal["accent"]), 1))
        p.setBrush(QColor(pal["accent"]) if lifted else QColor("#EEF3FA"))
        p.drawRoundedRect(r, 5, 5)
        p.setPen(QColor("#FFFFFF") if lifted else QColor("#2B3A52"))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, ELEMENTS[e])

    # ---- dragging
    def _slot_at(self, pos: QPointF) -> str | None:
        for slot, z in self._zones().items():
            if z.adjusted(-6, -6, 6, 6).contains(pos):
                return slot
        return None

    def mousePressEvent(self, e) -> None:
        pos = e.position()
        for el, r in self._chip_rects().items():
            if r.contains(pos):
                self._drag = el
                self._drag_pos = pos
                self._hover_slot = self.layout_map[el]
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                self.update()
                return

    def mouseMoveEvent(self, e) -> None:
        pos = e.position()
        if self._drag is not None:
            self._drag_pos = pos
            self._hover_slot = self._slot_at(pos)
            self.update()
        else:
            over = any(r.contains(pos) for r in self._chip_rects().values())
            self.setCursor(Qt.CursorShape.OpenHandCursor if over else Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, _e) -> None:
        if self._drag is None:
            return
        if self._hover_slot in SLOTS and self.layout_map[self._drag] != self._hover_slot:
            self.layout_map[self._drag] = self._hover_slot
            self.changed.emit(dict(self.layout_map))
        self._drag = None
        self._hover_slot = None
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()


class LayoutDesigner(QWidget):
    """Starting layouts as buttons, and the page to drag blocks around on."""
    changed = Signal(dict, str)          # layout, preset name ("custom" once dragged)

    def __init__(self, layout: dict, preset: str = "classic", parent: QWidget | None = None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.preset_buttons: dict[str, QPushButton] = {}
        for key, (name, _) in PRESETS.items():
            b = QPushButton(name)
            b.setCheckable(True)
            b.setChecked(key == preset)
            b.clicked.connect(lambda _=False, k=key: self.use_preset(k))
            row.addWidget(b)
            self.preset_buttons[key] = b
        row.addStretch(1)
        v.addLayout(row)
        self.canvas = PageCanvas(layout)
        self.canvas.changed.connect(self._dragged)
        v.addWidget(self.canvas, 1)
        v.addWidget(hint("Drag a block onto another spot; it snaps into place. Blocks in the same spot stack. "
                         "Bill to and Invoice details only appear on invoices (Bill to shows as "
                         "“Prepared for” on timesheets)."))

    def use_preset(self, key: str) -> None:
        for k, b in self.preset_buttons.items():
            b.setChecked(k == key)
        layout = dict(PRESETS[key][1])
        self.canvas.set_layout(layout)
        self.changed.emit(layout, key)

    def _dragged(self, layout: dict) -> None:
        for b in self.preset_buttons.values():
            b.setChecked(False)
        self.changed.emit(layout, "custom")

    def current_layout(self) -> dict:
        return dict(self.canvas.layout_map)
