"""Timesheet mode: who it's for, title, the editable step table and time options."""
from __future__ import annotations

import re

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton, QVBoxLayout, QWidget)

from ..model import build_spec
from ..pdf import build_timesheet_pdf
from ..timefmt import ROUNDING, TIME_FORMATS, fmt_date, fmt_duration
from .dialogs import ColumnsDialog
from .step_table import StepTable
from .widgets import combo, hint, section, set_combo


def safe_filename(text: str) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text).strip().rstrip(".")
    return re.sub(r"\s+", "_", text) or "Timesheet"


class TimesheetPanel(QWidget):
    changed = Signal()

    def __init__(self, main, parent: QWidget | None = None):
        super().__init__(parent)
        self.main = main
        self.keys: list[str] = []
        self.doc_text: dict[tuple, tuple[str, str]] = {}
        self.client_for: dict[tuple, str] = {}
        self._loading = False
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        v.addWidget(section("Document"))
        f = QFormLayout()
        self.client = QComboBox()
        self.client.currentIndexChanged.connect(self._client_changed)
        f.addRow("Prepared for", self.client)
        self.title = QLineEdit()
        self.title.textEdited.connect(self._text_edited)
        self.desc = QPlainTextEdit()
        self.desc.setFixedHeight(60)
        self.desc.textChanged.connect(self._text_edited)
        f.addRow("Title", self.title)
        f.addRow("Description", self.desc)
        v.addLayout(f)

        head = QHBoxLayout()
        head.addWidget(section("Table"), 1)
        cols = QPushButton("Columns…")
        cols.clicked.connect(self.edit_columns)
        head.addWidget(cols)
        v.addLayout(head)
        self.pick_row = QWidget()
        h = QHBoxLayout(self.pick_row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(QLabel("Editing"))
        self.pick = QComboBox()
        self.pick.currentIndexChanged.connect(self._show_table)
        h.addWidget(self.pick, 1)
        v.addWidget(self.pick_row)
        self.table = StepTable()
        self.table.setMinimumHeight(230)
        self.table.changed.connect(self.changed)
        self.table.problem.connect(self._problem)
        v.addWidget(self.table, 1)
        btns = QHBoxLayout()
        for text, tip, fn in (("+ Row", "Add a row", self.table.add_row),
                              ("Remove", "Remove the selected rows", self.table.remove_selected),
                              ("↑", "Move up", lambda: self.table.move_selected(-1)),
                              ("↓", "Move down", lambda: self.table.move_selected(1))):
            b = QPushButton(text, toolTip=tip)
            b.clicked.connect(fn)
            btns.addWidget(b)
        btns.addStretch(1)
        self.reset_btn = QPushButton("Reset to original", toolTip="Undo every edit to this log's table")
        self.reset_btn.clicked.connect(self.reset_table)
        btns.addWidget(self.reset_btn)
        v.addLayout(btns)
        self.problem = QLabel(objectName="Warn")
        self.problem.setWordWrap(True)
        self.problem.hide()
        v.addWidget(self.problem)
        self.problem_timer = QTimer(self, singleShot=True, interval=6000, timeout=self.problem.hide)
        v.addWidget(hint("Double-click a cell to edit it. Edits change the PDF only, never the log. "
                         "They also carry over to invoices made from the same logs."))

        v.addWidget(section("Time"))
        f = QFormLayout()
        opts = main.opts
        self.fmt = combo(TIME_FORMATS, opts.time_format)
        self.rounding = combo(ROUNDING, opts.rounding)
        self.each_row = QCheckBox("Round each row (otherwise each category's total)")
        self.layout_c = combo([("sections", "A section per log"), ("single", "One table")], opts.layout)
        self.layout_label = QLabel("Combined logs")
        self.cat_summary = QCheckBox("Add a “Time by category” table")
        for w in (self.fmt, self.rounding, self.layout_c):
            w.currentIndexChanged.connect(self._options_changed)
        for w in (self.each_row, self.cat_summary):
            w.toggled.connect(self._options_changed)
        f.addRow("Time format", self.fmt)
        f.addRow("Rounding", self.rounding)
        f.addRow("", self.each_row)
        f.addRow(self.layout_label, self.layout_c)
        f.addRow("", self.cat_summary)
        v.addLayout(f)
        self.round_note = QLabel(objectName="Note")
        v.addWidget(self.round_note)
        self.apply_options()
        self.reload_clients()

    # ---- options
    def apply_options(self) -> None:
        o = self.main.opts
        self._loading = True
        set_combo(self.fmt, o.time_format)
        set_combo(self.rounding, o.rounding)
        set_combo(self.layout_c, o.layout)
        self.each_row.setChecked(o.round_each_row)
        self.each_row.setVisible(o.rounding != "off")
        self.cat_summary.setChecked(o.category_summary)
        self._loading = False
        self.table.time_format = o.time_format
        self.table.refresh()

    def _options_changed(self, *_) -> None:
        if self._loading:
            return
        o = self.main.opts
        fmt_changed = o.time_format != self.fmt.currentData()
        o.time_format = self.fmt.currentData()
        o.rounding = self.rounding.currentData()
        o.round_each_row = self.each_row.isChecked()
        o.layout = self.layout_c.currentData()
        o.category_summary = self.cat_summary.isChecked()
        self.each_row.setVisible(o.rounding != "off")
        if fmt_changed:
            self.table.time_format = o.time_format
            self.table.refresh()
        self.changed.emit()

    def edit_columns(self) -> None:
        d = ColumnsDialog(self.main.opts.columns, self)
        if d.exec():
            self.main.opts.columns = d.columns()
            self.changed.emit()

    # ---- clients
    def reload_clients(self) -> None:
        keep = self.client.currentData()
        self._loading = True
        self.client.clear()
        self.client.addItem("No one (leave out)", "")
        for c in self.main.data.clients:
            self.client.addItem(c.display, c.id)
        self.client.setCurrentIndex(max(0, self.client.findData(keep)))
        self._loading = False

    def _client_changed(self, *_) -> None:
        if self._loading or not self.keys:
            return
        self.client_for[tuple(self.keys)] = self.client.currentData() or ""
        self.changed.emit()

    # ---- logs
    def set_logs(self, keys: list[str]) -> None:
        logs = self.main.logs
        self.keys = sorted([k for k in keys if k in logs], key=lambda k: logs[k].sort_time)
        for k in self.keys:
            self.main.ensure_edits(k)
        title, desc = self._doc_text()
        self._loading = True
        self.title.setText(title)
        self.desc.setPlainText(desc)
        self.pick.clear()
        for k in self.keys:
            lg = logs[k]
            self.pick.addItem(f"{lg.title} — {fmt_date(lg.sort_time.date())}", k)
        key = tuple(self.keys)
        cid = self.client_for.get(key)
        if cid is None:
            labels = {logs[k].client for k in self.keys if logs[k].client}
            match = self.main.data.client_for_label(next(iter(labels))) if len(labels) == 1 else None
            cid = match.id if match else ""
        self.client.setCurrentIndex(max(0, self.client.findData(cid)))
        self._loading = False
        combined = len(self.keys) > 1
        self.pick_row.setVisible(combined)
        self.layout_label.setVisible(combined)
        self.layout_c.setVisible(combined)
        self._show_table()

    def _doc_text(self) -> tuple[str, str]:
        key = tuple(self.keys)
        if key in self.doc_text:
            return self.doc_text[key]
        if not self.keys:
            return "", ""
        first = self.main.logs[self.keys[0]]
        return (first.title, first.description) if len(self.keys) == 1 else (first.title, "")

    def _text_edited(self, *_) -> None:
        if self._loading or not self.keys:
            return
        self.doc_text[tuple(self.keys)] = (self.title.text(), self.desc.toPlainText())
        self.changed.emit()

    def _show_table(self, *_) -> None:
        if self._loading:
            return
        key = self.pick.currentData() if len(self.keys) > 1 else (self.keys[0] if self.keys else None)
        self.table.set_edits(self.main.edits.get(key) if key else None, self.main.opts.time_format)
        self.reset_btn.setEnabled(key is not None)

    def reset_table(self) -> None:
        e = self.table.edits
        if e is None or e.key not in self.main.logs:
            return
        e.reset(self.main.logs[e.key])
        self.table.refresh()
        self.changed.emit()

    def _problem(self, text: str) -> None:
        self.problem.setText(text)
        self.problem.show()
        self.problem_timer.start()

    # ---- building
    def has_document(self) -> bool:
        return bool(self.keys)

    def empty_message(self) -> str:
        return "Pick a time log on the left to see its timesheet here." if self.main.logs else \
            "No time logs yet. They appear here when a timed checklist finishes in Docket."

    def build(self, profile):
        entries = [(self.main.logs[k], self.main.edits[k]) for k in self.keys]
        spec = build_spec(entries, self.title.text().strip(), self.desc.toPlainText().strip(), self.main.opts)
        client = self.main.data.client(self.client.currentData() or "")
        prepared = (client.name or client.label, client.bill_to) if client else None
        result = build_timesheet_pdf(spec, profile, self.main.data.image_path(profile.logo),
                                     self.main.data.image_path(profile.watermark),
                                     self.main.author(profile), prepared)
        o = self.main.opts
        note = ""
        if o.rounding != "off":
            note = f"Actual {fmt_duration(spec.actual_seconds, o.time_format)} → " \
                   f"Rounded {fmt_duration(spec.billed_seconds, o.time_format)}"
        self.round_note.setText(note)
        return result

    def default_name(self) -> str:
        when = max(self.main.logs[k].sort_time for k in self.keys)
        return f"{safe_filename(self.title.text().strip() or 'Timesheet')}_{when:%Y-%m-%d}.pdf"

    def export(self) -> None:
        if not self.keys:
            return
        result = self.main.build_now()
        if result is None:
            return
        self.main.save_pdf(result.data, self.default_name())
