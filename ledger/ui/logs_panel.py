"""The list of Docket time logs (newest first), with ticks to pick several."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from ..logs import TimeLog
from ..timefmt import fmt_date, fmt_duration
from .widgets import hint

HINTS = {
    "timesheet": "Click a log to see its timesheet. Tick several to combine them.",
    "invoice": "Tick the logs to put on this invoice.",
    "locked": "This invoice has been sent, so its logs stay as they were.",
}


class LogsPanel(QWidget):
    selection_changed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 6, 4, 4)
        self.search = QLineEdit(placeholderText="Search logs or clients")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        v.addWidget(self.search)
        self.list = QListWidget()
        self.list.setSpacing(1)
        self.list.currentItemChanged.connect(lambda *_: self._emit())
        self.list.itemChanged.connect(lambda *_: self._emit())
        v.addWidget(self.list, 1)
        self.hint = hint(HINTS["timesheet"])
        v.addWidget(self.hint)
        self.folder_label = QLabel(objectName="Hint")
        self.folder_label.setWordWrap(True)
        v.addWidget(self.folder_label)
        self._loading = False
        self.mode = "timesheet"

    def _emit(self) -> None:
        if not self._loading:
            self.selection_changed.emit()

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.hint.setText(HINTS.get(mode, ""))

    def fill(self, logs: list[TimeLog], invoiced: dict[str, list[str]], select: str | None = None,
             ticked: set[str] | None = None) -> None:
        ticked = set(self.checked()) if ticked is None else ticked
        current = select or self.current()
        self._loading = True
        self.list.clear()
        for lg in logs:
            when = lg.sort_time
            bits = [f"{fmt_date(when.date())} {when:%H:%M}", fmt_duration(lg.total_seconds, "hms")]
            if lg.client:
                bits.append(lg.client)
            text = f"{lg.title}\n" + " · ".join(bits)
            if lg.key in invoiced:
                text += f"\n✓ Invoiced {', '.join(invoiced[lg.key])}"
            if lg.warning:
                text = "⚠ " + text
            it = QListWidgetItem(text)
            it.setData(Qt.ItemDataRole.UserRole, lg.key)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if lg.key in ticked else Qt.CheckState.Unchecked)
            tip = "\n".join(str(p) for p in lg.paths)
            if lg.template:
                tip += f"\nTemplate: {lg.template}"
            if lg.warning:
                tip += f"\n\n{lg.warning}"
            it.setToolTip(tip)
            self.list.addItem(it)
        if not logs:
            it = QListWidgetItem("No time logs yet.")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(it)
        target = None
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.ItemDataRole.UserRole) == current:
                target = self.list.item(i)
        if target is None and logs and self.mode == "timesheet":
            target = self.list.item(0)
        if target is not None:
            self.list.setCurrentItem(target)
        self._loading = False
        self._filter(self.search.text())

    def _filter(self, text: str) -> None:
        t = text.strip().lower()
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setHidden(bool(t) and t not in it.text().lower())

    def checked(self) -> list[str]:
        out = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            key = it.data(Qt.ItemDataRole.UserRole)
            if key and it.checkState() == Qt.CheckState.Checked:
                out.append(key)
        return out

    def current(self) -> str | None:
        it = self.list.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def set_ticked(self, keys: set[str], current: str | None = None) -> None:
        self._loading = True
        for i in range(self.list.count()):
            it = self.list.item(i)
            key = it.data(Qt.ItemDataRole.UserRole)
            if key:
                it.setCheckState(Qt.CheckState.Checked if key in keys else Qt.CheckState.Unchecked)
                if key == current:
                    self.list.setCurrentItem(it)
        self._loading = False
        self.selection_changed.emit()

    def set_enabled_ticks(self, enabled: bool) -> None:
        self._loading = True
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(Qt.ItemDataRole.UserRole):
                flags = it.flags()
                flags = flags | Qt.ItemFlag.ItemIsUserCheckable if enabled else flags & ~Qt.ItemFlag.ItemIsUserCheckable
                it.setFlags(flags)
        self._loading = False
