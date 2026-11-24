"""The editable table of steps for one log. Edits change the PDF only, never the log file."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem, QWidget

from ..model import EditRow, LogEdits
from ..timefmt import fmt_duration, parse_duration, parse_timestamp
from . import theme

COLS = [("included", ""), ("step", "Step"), ("category", "Category"), ("start", "Start"), ("end", "End"), ("duration", "Duration"),
        ("limit", "Limit"), ("done", "Done")]
TS = "%Y-%m-%d %H:%M:%S"


class StepTable(QTableWidget):
    changed = Signal()
    problem = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(0, len(COLS), parent)
        self.edits: LogEdits | None = None
        self.time_format = "hms"
        self._loading = False
        self.setHorizontalHeaderLabels([c[1] for c in COLS])
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed
                             | QAbstractItemView.EditTrigger.AnyKeyPressed)
        self.setAlternatingRowColors(False)
        self.setWordWrap(False)
        h = self.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.horizontalHeaderItem(0).setToolTip("Include this row in the PDF")
        self.horizontalHeaderItem(5).setToolTip("Type 1:30:00, 1:30 (h:mm), 1.5 (hours) or 90m.\n"
                                                "Changing Start or End works the duration out again.")
        self.itemChanged.connect(self._on_item_changed)

    # ---- loading
    def set_edits(self, edits: LogEdits | None, time_format: str) -> None:
        self.edits = edits
        self.time_format = time_format
        self.refresh()

    def refresh(self) -> None:
        self._loading = True
        try:
            rows = self.edits.rows if self.edits else []
            self.setRowCount(len(rows))
            for i, r in enumerate(rows):
                self._fill_row(i, r)
        finally:
            self._loading = False

    def _fill_row(self, i: int, r: EditRow) -> None:
        # Items are updated in place (never replaced), since this also runs while Qt is
        # still handling the edit that changed them.
        tint = QBrush(QColor(theme.current["edited"]))
        for c, (key, _) in enumerate(COLS):
            item = self.item(i, c)
            if item is None:
                item = QTableWidgetItem()
                self.setItem(i, c, item)
            if key == "included":
                item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                item.setCheckState(Qt.CheckState.Checked if r.included else Qt.CheckState.Unchecked)
            else:
                item.setText(self._text(key, r))
                if key == "duration":
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if r.manual or (key != "included" and r.edited(key)):
                item.setBackground(tint)
                item.setToolTip("Edited (PDF only)" if not r.manual else "Added by hand (PDF only)")
            else:
                item.setBackground(QBrush())
                item.setToolTip("")
            muted = not r.included and key != "included"
            item.setForeground(QBrush(QColor(theme.current["muted"])) if muted else QBrush())

    def _text(self, key: str, r: EditRow) -> str:
        if key in ("start", "end"):
            v = getattr(r, key)
            return v.strftime(TS) if v else ""
        if key == "duration":
            return fmt_duration(r.seconds, self.time_format)
        return str(getattr(r, key) or "")

    # ---- editing
    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or self.edits is None:
            return
        i, c = item.row(), item.column()
        if i >= len(self.edits.rows):
            return
        r = self.edits.rows[i]
        key = COLS[c][0]
        try:
            if key == "included":
                r.included = item.checkState() == Qt.CheckState.Checked
            elif key in ("start", "end"):
                setattr(r, key, parse_timestamp(item.text(), getattr(r, key) or r.start or r.end))
                r.override = None
            elif key == "duration":
                r.override = parse_duration(item.text())
            else:
                setattr(r, key, item.text().strip())
        except ValueError as e:
            self.problem.emit(str(e))
        self._loading = True
        try:
            self._fill_row(i, r)
        finally:
            self._loading = False
        self.changed.emit()

    def add_row(self) -> None:
        if self.edits is None:
            return
        last = self.edits.rows[-1] if self.edits.rows else None
        when = (last.end or last.start) if last else None
        self.edits.rows.append(EditRow(step="New step", category=last.category if last else "", start=when, end=when,
                                        override=0))
        self.refresh()
        row = len(self.edits.rows) - 1
        self.setCurrentCell(row, 1)
        self.editItem(self.item(row, 1))
        self.changed.emit()

    def remove_selected(self) -> None:
        if self.edits is None:
            return
        rows = sorted({i.row() for i in self.selectedIndexes()}, reverse=True)
        for i in rows:
            if 0 <= i < len(self.edits.rows):
                del self.edits.rows[i]
        if rows:
            self.refresh()
            self.changed.emit()

    def move_selected(self, delta: int) -> None:
        if self.edits is None:
            return
        rows = sorted({i.row() for i in self.selectedIndexes()})
        if len(rows) != 1:
            return
        i, j = rows[0], rows[0] + delta
        if 0 <= j < len(self.edits.rows):
            self.edits.rows[i], self.edits.rows[j] = self.edits.rows[j], self.edits.rows[i]
            self.refresh()
            self.selectRow(j)
            self.changed.emit()
