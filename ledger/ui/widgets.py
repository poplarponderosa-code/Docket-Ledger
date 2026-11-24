"""Small shared widgets: combos, labels, the app icon, an image picker and a two-way toggle."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFileDialog, QHBoxLayout, QLabel, QPushButton, QWidget)

IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.gif)"


def combo(choices: list[tuple[str, str]], value: str) -> QComboBox:
    c = QComboBox()
    for key, label in choices:
        c.addItem(label, key)
    c.setCurrentIndex(max(0, c.findData(value)))
    return c


def set_combo(c: QComboBox, value) -> None:
    c.blockSignals(True)
    c.setCurrentIndex(max(0, c.findData(value)))
    c.blockSignals(False)


def hint(text: str) -> QLabel:
    lab = QLabel(text, objectName="Hint")
    lab.setWordWrap(True)
    return lab


def section(text: str) -> QLabel:
    return QLabel(text.upper(), objectName="Section")


def restyle(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)


# ---- the app icon: an L with ledger lines ------------------------------------------------------------
def logo_path(size: float) -> QPainterPath:
    S = float(size)
    r = S * 0.16
    stem = QPainterPath()
    stem.addRoundedRect(QRectF(0, 0, S * 0.6, S), r, r)
    foot = QPainterPath()
    foot.addRoundedRect(QRectF(0, S * 0.58, S, S * 0.42), r, r)
    return stem.united(foot)


def app_icon(accent: str = "#3F6596", background: str = "#FFFFFF") -> QIcon:
    icon = QIcon()
    for size in (16, 20, 24, 32, 48, 64, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(accent))
        p.drawPath(logo_path(size))
        p.setBrush(QColor(background))
        bar = max(1.5, size * 0.1)
        for y, x, w in ((0.17, 0.17, 0.26), (0.36, 0.17, 0.26), (0.72, 0.17, 0.66)):
            p.drawRoundedRect(QRectF(size * x, size * y, size * w, bar), bar / 2, bar / 2)
        p.end()
        icon.addPixmap(pm)
    return icon


# ---- two-way toggle -----------------------------------------------------------------------------
class Segmented(QWidget):
    changed = Signal(str)

    def __init__(self, choices: list[tuple[str, str]], value: str, parent: QWidget | None = None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        for i, (key, label) in enumerate(choices):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setProperty("seg", True)
            b.setProperty("segpos", "first" if i == 0 else ("last" if i == len(choices) - 1 else "mid"))
            b.setChecked(key == value)
            b.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
            self.group.addButton(b)
            self.buttons[key] = b
            h.addWidget(b)

    def set_value(self, key: str) -> None:
        b = self.buttons.get(key)
        if b:
            b.setChecked(True)

    def value(self) -> str:
        return next((k for k, b in self.buttons.items() if b.isChecked()), "")


# ---- image picker row --------------------------------------------------------------------------
class ImagePicker(QWidget):
    """Choose / Remove an image. Images are copied into Ledger's own folder."""
    changed = Signal()

    def __init__(self, data, name: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.data = data
        self.name = name
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        self.thumb = QLabel()
        self.thumb.setFixedSize(54, 30)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        choose = QPushButton("Choose…")
        choose.clicked.connect(self._choose)
        self.clear_btn = QPushButton("Remove")
        self.clear_btn.clicked.connect(self._clear)
        h.addWidget(self.thumb)
        h.addWidget(choose)
        h.addWidget(self.clear_btn)
        h.addStretch(1)
        self._update()

    def path(self) -> Path | None:
        return self.data.image_path(self.name)

    def _update(self) -> None:
        p = self.path()
        if p:
            pm = QPixmap(str(p))
            self.thumb.setPixmap(pm.scaled(54, 30, Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation))
        else:
            self.thumb.setPixmap(QPixmap())
            self.thumb.setText("None")
        self.clear_btn.setEnabled(bool(self.name))

    def _choose(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose an image", str(Path.home() / "Pictures"), IMAGE_FILTER)
        if path:
            self.name = self.data.import_image(Path(path))
            self._update()
            self.changed.emit()

    def _clear(self) -> None:
        self.name = ""
        self._update()
        self.changed.emit()
