"""Shows the real PDF pages (rendered from the exact bytes that will be exported)."""
from __future__ import annotations

import pypdfium2 as pdfium
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QLabel, QScrollArea, QVBoxLayout, QWidget

ZOOMS = [("fit", "Fit width"), ("50", "50%"), ("75", "75%"), ("100", "100%"), ("125", "125%"), ("150", "150%")]


class PreviewView(QScrollArea):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("PreviewArea")
        self.setWidgetResizable(True)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._body = QWidget(objectName="PreviewBody")
        self._layout = QVBoxLayout(self._body)
        self._layout.setContentsMargins(20, 20, 20, 20)
        self._layout.setSpacing(18)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.setWidget(self._body)
        self._labels: list[QLabel] = []
        self._doc: pdfium.PdfDocument | None = None
        self._data: bytes = b""
        self.zoom = "fit"
        self._resize_timer = QTimer(self, singleShot=True, interval=120, timeout=self._render)
        self._message = QLabel("", objectName="Empty", alignment=Qt.AlignmentFlag.AlignCenter)
        self._message.setWordWrap(True)
        self._layout.addWidget(self._message)

    # ---- public
    def show_message(self, text: str) -> None:
        self._doc = None
        self._data = b""
        self._clear_pages()
        self._message.setText(text)
        self._message.show()

    def set_pdf(self, data: bytes) -> None:
        self._data = data
        try:
            self._doc = pdfium.PdfDocument(data)
        except Exception as e:      # noqa: BLE001
            self.show_message(f"The preview couldn't be drawn.\n{e}")
            return
        self._message.hide()
        self._render()

    def set_zoom(self, zoom: str) -> None:
        self.zoom = zoom
        self._render()

    # ---- drawing
    def _clear_pages(self) -> None:
        for lab in self._labels:
            lab.deleteLater()
        self._labels = []

    def _render(self) -> None:
        if self._doc is None:
            return
        vbar = self.verticalScrollBar()
        ratio = vbar.value() / vbar.maximum() if vbar.maximum() else 0.0
        dpr = self.devicePixelRatioF()
        n = len(self._doc)
        while len(self._labels) < n:
            lab = QLabel()
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            shadow = QGraphicsDropShadowEffect(lab)
            shadow.setBlurRadius(18)
            shadow.setOffset(0, 2)
            shadow.setColor(QColor(0, 0, 0, 60))
            lab.setGraphicsEffect(shadow)
            self._layout.addWidget(lab, 0, Qt.AlignmentFlag.AlignHCenter)
            self._labels.append(lab)
        while len(self._labels) > n:
            self._labels.pop().deleteLater()
        for i in range(n):
            page = self._doc[i]
            w_pt, _ = page.get_size()
            if self.zoom == "fit":
                avail = max(200, self.viewport().width() - 44)
                scale = avail / w_pt
            else:
                scale = int(self.zoom) / 100 * 96 / 72
            pil = page.render(scale=scale * dpr).to_pil().convert("RGB")
            img = QImage(pil.tobytes("raw", "RGB"), pil.width, pil.height, pil.width * 3,
                         QImage.Format.Format_RGB888).copy()
            pix = QPixmap.fromImage(img)
            pix.setDevicePixelRatio(dpr)
            self._labels[i].setPixmap(pix)
            self._labels[i].setFixedSize(int(pil.width / dpr), int(pil.height / dpr))
        QTimer.singleShot(0, lambda: vbar.setValue(int(ratio * vbar.maximum())))

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        if self.zoom == "fit":
            self._resize_timer.start()
