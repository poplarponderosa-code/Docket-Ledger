"""Dialogs: columns, business profile, client, saved items, settings, client matching, paid date."""
from __future__ import annotations

import copy
import datetime as dt
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QDateEdit, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit,
                               QPushButton, QRadioButton, QSlider, QSpinBox, QTableWidget, QTableWidgetItem,
                               QTabWidget, QVBoxLayout, QWidget)

from .. import fonts
from ..colors import DEFAULT_ACCENT, logo_colors, resolve_accent
from ..model import COLUMN_NAMES, default_columns, normalise_columns
from ..money import CURRENCIES
from ..store import (DEFAULT_NUMBER_FORMAT, PAGE_NUMBER_POSITIONS, PAGE_NUMBER_STYLES, Client, Data, Profile,
                     SavedItem, Settings, format_number, new_id, number_format_ok, reset_period)
from ..timefmt import ROUNDING, TIME_FORMATS
from .layout_designer import LayoutDesigner
from .widgets import ImagePicker, combo, hint, section

NUMBER_FORMATS = [
    ("{YYYY}-{MM}-{DD}-{NN}", "Date and counter (2026-11-23-01)"),
    ("{YYYY}-{NNN}", "Year and counter (2026-001)"),
    ("INV-{NNNN}", "INV and counter (INV-0001)"),
    ("{YY}{MM}-{NN}", "Short date (2611-01)"),
]


def currency_choices() -> list[tuple[str, str]]:
    return [(code, f"{code} — {name}") for code, (_, _, name) in CURRENCIES.items()]


def buttons(dialog: QDialog, ok_text: str = "Save") -> QDialogButtonBox:
    bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    bb.button(QDialogButtonBox.StandardButton.Ok).setText(ok_text)
    bb.accepted.connect(dialog.accept)
    bb.rejected.connect(dialog.reject)
    return bb


# ---- columns ---------------------------------------------------------------------------------------
class ColumnsDialog(QDialog):
    """Turn columns on and off, drag to reorder, double-click to rename."""

    def __init__(self, columns: list[dict], parent: QWidget | None = None, title: str = "Columns"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(340, 400)
        v = QVBoxLayout(self)
        v.addWidget(hint("Tick the columns to show in the PDF. Drag to change their order; "
                         "double-click a name to rename its heading."))
        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        v.addWidget(self.list, 1)
        v.addWidget(hint("Checklist only appears when several logs share one table; Category only when steps "
                         "have categories."))
        reset = QPushButton("Restore defaults")
        reset.clicked.connect(lambda: self._load(default_columns()))
        row = QHBoxLayout()
        row.addWidget(reset)
        row.addStretch(1)
        v.addLayout(row)
        v.addWidget(buttons(self, "OK"))
        self._load(normalise_columns(columns))

    def _load(self, columns: list[dict]) -> None:
        self.list.clear()
        for c in columns:
            it = QListWidgetItem(c["label"])
            it.setData(Qt.ItemDataRole.UserRole, c["key"])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable
                        | Qt.ItemFlag.ItemIsDragEnabled)
            it.setCheckState(Qt.CheckState.Checked if c["visible"] else Qt.CheckState.Unchecked)
            it.setToolTip(f"{COLUMN_NAMES[c['key']]} column")
            self.list.addItem(it)

    def columns(self) -> list[dict]:
        out = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            key = it.data(Qt.ItemDataRole.UserRole)
            out.append({"key": key, "label": it.text().strip() or COLUMN_NAMES[key],
                        "visible": it.checkState() == Qt.CheckState.Checked})
        return out


# ---- tax lines --------------------------------------------------------------------------------------
class TaxTable(QWidget):
    """Name and rate of each tax line (e.g. GST 5). Clients turn the ones that apply on."""

    def __init__(self, taxes: list[dict], parent: QWidget | None = None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Tax name", "Rate %"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumHeight(110)
        v.addWidget(self.table)
        row = QHBoxLayout()
        add = QPushButton("+ Add tax")
        add.clicked.connect(lambda: self._add({"id": new_id(), "name": "", "rate": ""}, edit=True))
        rem = QPushButton("Remove")
        rem.clicked.connect(self._remove)
        row.addWidget(add)
        row.addWidget(rem)
        row.addStretch(1)
        v.addLayout(row)
        for t in taxes:
            self._add(t)

    def _add(self, t: dict, edit: bool = False) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        name = QTableWidgetItem(t.get("name", ""))
        name.setData(Qt.ItemDataRole.UserRole, t.get("id") or new_id())
        self.table.setItem(r, 0, name)
        self.table.setItem(r, 1, QTableWidgetItem(str(t.get("rate", ""))))
        if edit:
            self.table.setCurrentCell(r, 0)
            self.table.editItem(name)

    def _remove(self) -> None:
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(r)

    def taxes(self) -> list[dict]:
        out = []
        for r in range(self.table.rowCount()):
            name = self.table.item(r, 0)
            rate = self.table.item(r, 1)
            if name is None or not name.text().strip():
                continue
            out.append({"id": name.data(Qt.ItemDataRole.UserRole) or new_id(), "name": name.text().strip(),
                        "rate": (rate.text() if rate else "").strip().rstrip("%")})
        return out


# ---- header colour -----------------------------------------------------------------------------------
class AccentPicker(QWidget):
    """'Match my logo' or a chosen colour, with the logo's own colours as one-click swatches."""

    def __init__(self, accent: str, logo_path: Path | None, on_change: Callable[[], None],
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.accent = accent
        self.on_change = on_change
        self.logo_path = logo_path
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.auto = QRadioButton("Match my logo")
        self.custom = QRadioButton("Choose a colour")
        self.auto.setChecked(not accent)
        self.custom.setChecked(bool(accent))
        self.auto.toggled.connect(self._mode)
        v.addWidget(self.auto)
        v.addWidget(self.custom)
        self.swatches = QHBoxLayout()
        v.addLayout(self.swatches)
        self.refresh(logo_path)

    def refresh(self, logo_path: Path | None) -> None:
        self.logo_path = logo_path
        while self.swatches.count():
            w = self.swatches.takeAt(0).widget()
            if w:
                w.deleteLater()
        cols = logo_colors(logo_path, 4)
        for c in cols + ([DEFAULT_ACCENT] if DEFAULT_ACCENT not in cols else []):
            b = QPushButton()
            b.setProperty("swatch", True)
            b.setToolTip(c)
            b.setFixedSize(30, 24)
            b.setStyleSheet(f"background: {c}; border: 2px solid {'#000' if c == self.current() else c};"
                            "border-radius: 6px;")
            b.clicked.connect(lambda _=False, col=c: self._set(col))
            self.swatches.addWidget(b)
        more = QPushButton("More…")
        more.clicked.connect(self._pick)
        self.swatches.addWidget(more)
        self.swatches.addStretch(1)

    def current(self) -> str:
        return resolve_accent(self.accent, self.logo_path)

    def _set(self, col: str) -> None:
        self.accent = col
        self.custom.setChecked(True)
        self.refresh(self.logo_path)
        self.on_change()

    def _pick(self) -> None:
        col = QColorDialog.getColor(QColor(self.current()), self, "Header colour")
        if col.isValid():
            self._set(col.name().upper())

    def _mode(self, auto: bool) -> None:
        if auto:
            self.accent = ""
            self.refresh(self.logo_path)
            self.on_change()

    def value(self) -> str:
        return "" if self.auto.isChecked() else (self.accent or self.current())


# ---- business profile ----------------------------------------------------------------------------------
class ProfileDialog(QDialog):
    """Your business: details, logo and colours, layout, footer, page and taxes. The preview updates live."""

    def __init__(self, data: Data, name: str, on_preview: Callable[[Profile], None], parent: QWidget | None = None):
        super().__init__(parent)
        self.data = data
        self.original_name = name
        self.profile = copy.deepcopy(data.profile(name))
        self.on_preview = on_preview
        self._ready = False
        self.setWindowTitle("Business profile")
        self.resize(560, 680)
        p = self.profile
        v = QVBoxLayout(self)
        top = QFormLayout()
        self.name_edit = QLineEdit(p.name)
        self.name_edit.textChanged.connect(self._changed)
        top.addRow("Profile name", self.name_edit)
        v.addLayout(top)
        tabs = QTabWidget()
        v.addWidget(tabs, 1)

        # business details
        w = QWidget()
        f = QFormLayout(w)
        self.contact = QPlainTextEdit(p.contact)
        self.contact.setPlaceholderText("Business name\nAddress\nEmail · Phone")
        self.contact.setFixedHeight(110)
        f.addRow("Your details", self.contact)
        f.addRow("", hint("The first line is shown in bold."))
        self.tax_number = QLineEdit(p.tax_number)
        self.tax_number.setPlaceholderText("e.g. GST/HST no. 12345 6789 RT0001")
        f.addRow("Tax or business no.", self.tax_number)
        self.payment = QPlainTextEdit(p.payment)
        self.payment.setPlaceholderText("How to pay you, e.g. e-Transfer to you@example.com")
        self.payment.setFixedHeight(80)
        f.addRow("Payment instructions", self.payment)
        f.addRow("", hint("The tax number and payment instructions appear on invoices only."))
        for wdg in (self.contact, self.payment):
            wdg.textChanged.connect(self._changed)
        self.tax_number.textChanged.connect(self._changed)
        tabs.addTab(w, "Business")

        # logo and colours
        w = QWidget()
        f = QFormLayout(w)
        self.logo = ImagePicker(data, p.logo)
        self.logo.changed.connect(self._logo_changed)
        f.addRow("Logo", self.logo)
        self.logo_h = QDoubleSpinBox()
        self.logo_h.setRange(5, 60)
        self.logo_h.setSuffix(" mm")
        self.logo_h.setValue(p.logo_height_mm)
        self.logo_h.valueChanged.connect(self._changed)
        f.addRow("Logo height", self.logo_h)
        f.addRow("", hint("PNG with a transparent background works best."))
        self.accent = AccentPicker(p.accent, data.image_path(p.logo), self._changed)
        f.addRow("Header colour", self.accent)
        self.header_text = combo([("auto", "Automatic (most readable)"), ("light", "White"), ("dark", "Dark")],
                                 p.header_text)
        self.header_text.currentIndexChanged.connect(self._changed)
        f.addRow("Header text", self.header_text)
        tabs.addTab(w, "Logo and colour")

        # layout
        w = QWidget()
        lv = QVBoxLayout(w)
        self.designer = LayoutDesigner(p.layout, p.preset)
        self.designer.changed.connect(self._layout_changed)
        lv.addWidget(self.designer)
        tabs.addTab(w, "Layout")

        # footer and watermark
        w = QWidget()
        f = QFormLayout(w)
        self.footer = QPlainTextEdit(p.footer)
        self.footer.setPlaceholderText("A thank-you, terms, or any other note")
        self.footer.setFixedHeight(90)
        self.footer.textChanged.connect(self._changed)
        f.addRow("Footer", self.footer)
        f.addRow("", hint("Shown at the bottom of every page."))
        self.watermark = ImagePicker(data, p.watermark)
        self.watermark.changed.connect(self._changed)
        f.addRow("Watermark", self.watermark)
        self.wm_size = self._slider(10, 100, p.watermark_size, "%")
        f.addRow("Watermark size", self.wm_size[0])
        self.wm_opacity = self._slider(2, 60, p.watermark_opacity, "%")
        f.addRow("Watermark strength", self.wm_opacity[0])
        tabs.addTab(w, "Footer")

        # page
        w = QWidget()
        f = QFormLayout(w)
        self.page_size = combo([("letter", "Letter"), ("a4", "A4")], p.page_size)
        self.orientation = combo([("portrait", "Portrait"), ("landscape", "Landscape")], p.orientation)
        self.margins = combo([("narrow", "Narrow"), ("normal", "Normal"), ("wide", "Wide")], p.margins)
        fams = [("", f"Default ({fonts.default_family()})")] + [(x, x) for x in fonts.families()]
        self.heading_font = combo(fams, p.heading_font)
        self.body_font = combo(fams, p.body_font)
        self.font_size = combo([("small", "Small"), ("normal", "Normal"), ("large", "Large")], p.font_size)
        self.page_numbers = combo(PAGE_NUMBER_POSITIONS, p.page_numbers)
        self.pn_style = combo(PAGE_NUMBER_STYLES, p.page_number_style)
        for c in (self.page_size, self.orientation, self.margins, self.heading_font, self.body_font,
                  self.font_size, self.page_numbers, self.pn_style):
            c.currentIndexChanged.connect(self._changed)
        f.addRow("Page size", self.page_size)
        f.addRow("Orientation", self.orientation)
        f.addRow("Margins", self.margins)
        f.addRow("Heading font", self.heading_font)
        f.addRow("Body font", self.body_font)
        f.addRow("Text size", self.font_size)
        f.addRow("Page numbers", self.page_numbers)
        f.addRow("Number style", self.pn_style)
        self.pn_first = QCheckBox("Number the first page")
        self.pn_first.setChecked(p.page_number_first)
        self.show_range = QCheckBox("Timesheets: show the period covered")
        self.show_range.setChecked(p.show_date_range)
        self.show_gen = QCheckBox("Timesheets: show the date generated")
        self.show_gen.setChecked(p.show_generated)
        for cb in (self.pn_first, self.show_range, self.show_gen):
            cb.toggled.connect(self._changed)
            f.addRow("", cb)
        tabs.addTab(w, "Page")

        # taxes
        w = QWidget()
        tv = QVBoxLayout(w)
        tv.addWidget(hint("Add the taxes you charge, e.g. GST 5 or VAT 20. Each client then turns on the ones "
                          "that apply to them, and you can still switch them per invoice."))
        self.taxes = TaxTable(p.taxes)
        self.taxes.table.itemChanged.connect(self._changed)
        tv.addWidget(self.taxes)
        tv.addStretch(1)
        tabs.addTab(w, "Taxes")

        v.addWidget(buttons(self))
        self._ready = True

    def _slider(self, lo: int, hi: int, value: int, suffix: str) -> tuple[QWidget, QSlider]:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(lo, hi)
        s.setValue(int(value))
        lab = QLabel(f"{int(value)}{suffix}", objectName="Muted")
        lab.setFixedWidth(40)
        s.valueChanged.connect(lambda val: lab.setText(f"{val}{suffix}"))
        s.valueChanged.connect(self._changed)
        h.addWidget(s, 1)
        h.addWidget(lab)
        return w, s

    def _logo_changed(self) -> None:
        self.accent.refresh(self.data.image_path(self.logo.name))
        self._changed()

    def _layout_changed(self, layout: dict, preset: str) -> None:
        self.profile.layout = layout
        self.profile.preset = preset
        self._changed()

    def current(self) -> Profile:
        p = self.profile
        p.name = self.name_edit.text().strip() or self.original_name
        p.contact = self.contact.toPlainText()
        p.tax_number = self.tax_number.text().strip()
        p.payment = self.payment.toPlainText()
        p.logo = self.logo.name
        p.logo_height_mm = self.logo_h.value()
        p.accent = self.accent.value()
        p.header_text = self.header_text.currentData()
        p.layout = self.designer.current_layout()
        p.footer = self.footer.toPlainText()
        p.watermark = self.watermark.name
        p.watermark_size = self.wm_size[1].value()
        p.watermark_opacity = self.wm_opacity[1].value()
        p.page_size = self.page_size.currentData()
        p.orientation = self.orientation.currentData()
        p.margins = self.margins.currentData()
        p.heading_font = self.heading_font.currentData()
        p.body_font = self.body_font.currentData()
        p.font_size = self.font_size.currentData()
        p.page_numbers = self.page_numbers.currentData()
        p.page_number_style = self.pn_style.currentData()
        p.page_number_first = self.pn_first.isChecked()
        p.show_date_range = self.show_range.isChecked()
        p.show_generated = self.show_gen.isChecked()
        p.taxes = self.taxes.taxes()
        return Profile.from_dict(copy.deepcopy(p.to_dict()))

    def _changed(self, *_) -> None:
        if self._ready:
            self.on_preview(self.current())


# ---- client --------------------------------------------------------------------------------------------
class ClientDialog(QDialog):
    def __init__(self, data: Data, client: Client | None, known_categories: list[str], profile: Profile,
                 parent: QWidget | None = None, label: str = ""):
        super().__init__(parent)
        self.data = data
        self.client = copy.deepcopy(client) if client else Client(label=label, currency=data.settings.currency,
                                                                   terms_days=data.settings.terms_days)
        c = self.client
        self.setWindowTitle("Client" if client else "New client")
        self.resize(520, 640)
        v = QVBoxLayout(self)
        tabs = QTabWidget()
        v.addWidget(tabs, 1)

        w = QWidget()
        f = QFormLayout(w)
        self.label = QLineEdit(c.label)
        self.label.setPlaceholderText("Short label, e.g. Acme")
        f.addRow("Client label", self.label)
        f.addRow("", hint("This label appears in Docket and time logs. Your client's details stay in Ledger."))
        if c.aliases:
            f.addRow("Also matches", QLabel(", ".join(c.aliases), objectName="Muted"))
        self.name = QLineEdit(c.name)
        self.name.setPlaceholderText("Name shown on invoices")
        f.addRow("Name", self.name)
        self.bill_to = QPlainTextEdit(c.bill_to)
        self.bill_to.setPlaceholderText("Attention line, address…")
        self.bill_to.setFixedHeight(90)
        f.addRow("Bill to", self.bill_to)
        self.email = QLineEdit(c.email)
        f.addRow("Email", self.email)
        self.currency = combo(currency_choices(), c.currency)
        f.addRow("Currency", self.currency)
        self.terms = QSpinBox()
        self.terms.setRange(0, 365)
        self.terms.setSuffix(" days")
        self.terms.setSpecialValueText("Due on receipt")
        self.terms.setValue(int(c.terms_days))
        f.addRow("Payment terms", self.terms)
        self.notes = QPlainTextEdit(c.notes)
        self.notes.setFixedHeight(60)
        self.notes.setPlaceholderText("Private notes (never printed)")
        f.addRow("Notes", self.notes)
        tabs.addTab(w, "Details")

        w = QWidget()
        rv = QVBoxLayout(w)
        rv.addWidget(hint("Hourly rate for each category of work. Categories come from your Docket time logs; "
                          "you can add your own. The default rate covers anything without its own rate."))
        f2 = QFormLayout()
        self.default_rate = QLineEdit(c.default_rate)
        self.default_rate.setPlaceholderText("e.g. 75")
        f2.addRow("Default rate", self.default_rate)
        rv.addLayout(f2)
        self.rates = QTableWidget(0, 2)
        self.rates.setHorizontalHeaderLabels(["Category", "Rate per hour"])
        self.rates.verticalHeader().setVisible(False)
        self.rates.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        rv.addWidget(self.rates, 1)
        names = list(c.rates)
        lower = {n.lower() for n in names}
        for k in known_categories:
            if k and k.lower() not in lower:
                names.append(k)
                lower.add(k.lower())
        for n in names:
            self._add_rate(n, str(c.rates.get(n, "")))
        row = QHBoxLayout()
        add = QPushButton("+ Category")
        add.clicked.connect(lambda: self._add_rate("", "", edit=True))
        rem = QPushButton("Remove")
        rem.clicked.connect(lambda: [self.rates.removeRow(r) for r in
                                     sorted({i.row() for i in self.rates.selectedIndexes()}, reverse=True)])
        row.addWidget(add)
        row.addWidget(rem)
        row.addStretch(1)
        rv.addLayout(row)
        tabs.addTab(w, "Rates")

        w = QWidget()
        tv = QVBoxLayout(w)
        self.tax_boxes: list[tuple[str, QCheckBox]] = []
        if profile.taxes:
            tv.addWidget(hint("Taxes that apply to this client. They're switched on for new invoices; you can "
                              "still change them per invoice."))
            for t in profile.taxes:
                cb = QCheckBox(f"{t['name']} ({t['rate']}%)")
                cb.setChecked(t["id"] in c.taxes)
                tv.addWidget(cb)
                self.tax_boxes.append((t["id"], cb))
        else:
            tv.addWidget(hint("No tax lines yet. Add them in your business profile (Taxes tab)."))
        tv.addStretch(1)
        tabs.addTab(w, "Taxes")

        v.addWidget(buttons(self))

    def _add_rate(self, name: str, rate: str, edit: bool = False) -> None:
        r = self.rates.rowCount()
        self.rates.insertRow(r)
        self.rates.setItem(r, 0, QTableWidgetItem(name))
        self.rates.setItem(r, 1, QTableWidgetItem(rate))
        if edit:
            self.rates.setCurrentCell(r, 0)
            self.rates.editItem(self.rates.item(r, 0))

    def accept(self) -> None:
        if not self.label.text().strip() and not self.name.text().strip():
            self.label.setFocus()
            self.label.setPlaceholderText("Give the client a label or a name")
            return
        super().accept()

    def result_client(self) -> Client:
        c = self.client
        c.label = self.label.text().strip()
        c.name = self.name.text().strip()
        c.bill_to = self.bill_to.toPlainText().strip()
        c.email = self.email.text().strip()
        c.currency = self.currency.currentData()
        c.terms_days = self.terms.value()
        c.notes = self.notes.toPlainText().strip()
        c.default_rate = self.default_rate.text().strip()
        rates = {}
        for r in range(self.rates.rowCount()):
            n = self.rates.item(r, 0)
            v = self.rates.item(r, 1)
            name = n.text().strip() if n else ""
            if name:
                rates[name] = (v.text() if v else "").strip()
        c.rates = rates
        c.taxes = [tid for tid, cb in self.tax_boxes if cb.isChecked()]
        return c


# ---- saved items -----------------------------------------------------------------------------------------
class ItemsDialog(QDialog):
    KINDS = [("hours", "Hours"), ("qty", "Quantity"), ("fixed", "Fixed price")]

    def __init__(self, data: Data, parent: QWidget | None = None):
        super().__init__(parent)
        self.data = data
        self.setWindowTitle("Saved items")
        self.resize(640, 420)
        v = QVBoxLayout(self)
        v.addWidget(hint("Services you invoice often. Typing in an invoice's Description suggests them, and "
                         "picking one fills in the rest."))
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Description", "Type", "Unit", "Price / rate", "Category"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        v.addWidget(self.table, 1)
        row = QHBoxLayout()
        add = QPushButton("+ Item")
        add.clicked.connect(lambda: self._add(SavedItem(), edit=True))
        rem = QPushButton("Remove")
        rem.clicked.connect(lambda: [self.table.removeRow(r) for r in
                                     sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)])
        row.addWidget(add)
        row.addWidget(rem)
        row.addStretch(1)
        v.addLayout(row)
        v.addWidget(buttons(self))
        for it in data.items:
            self._add(it)

    def _add(self, it: SavedItem, edit: bool = False) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        d = QTableWidgetItem(it.description)
        d.setData(Qt.ItemDataRole.UserRole, it.id)
        self.table.setItem(r, 0, d)
        self.table.setCellWidget(r, 1, combo(self.KINDS, it.kind))
        self.table.setItem(r, 2, QTableWidgetItem(it.unit))
        self.table.setItem(r, 3, QTableWidgetItem(it.price))
        self.table.setItem(r, 4, QTableWidgetItem(it.category))
        if edit:
            self.table.setCurrentCell(r, 0)
            self.table.editItem(d)

    def accept(self) -> None:
        items = []
        for r in range(self.table.rowCount()):
            d = self.table.item(r, 0)
            if d is None or not d.text().strip():
                continue
            kind_w = self.table.cellWidget(r, 1)
            items.append(SavedItem(id=d.data(Qt.ItemDataRole.UserRole) or new_id(), description=d.text().strip(),
                                   kind=kind_w.currentData() if kind_w else "hours",
                                   unit=(self.table.item(r, 2).text() if self.table.item(r, 2) else "").strip(),
                                   price=(self.table.item(r, 3).text() if self.table.item(r, 3) else "").strip(),
                                   category=(self.table.item(r, 4).text() if self.table.item(r, 4) else "").strip()))
        self.data.items = items
        self.data.save_items()
        super().accept()


# ---- client matching -----------------------------------------------------------------------------------
class ClientMatchDialog(QDialog):
    """A log's client label doesn't match any client: pick one, make a new one, or skip."""

    def __init__(self, data: Data, label: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Which client?")
        self.choice = "skip"
        v = QVBoxLayout(self)
        v.addWidget(QLabel(f"This time log is for client “{label}”, which doesn't match any client "
                           "in Docket Ledger yet."))
        self.pick = QComboBox()
        for c in data.clients:
            self.pick.addItem(c.display + (f"  ({c.label})" if c.label and c.label != c.display else ""), c.id)
        self.remember = QCheckBox(f"Remember “{label}” for this client")
        self.remember.setChecked(True)
        if data.clients:
            row = QHBoxLayout()
            row.addWidget(self.pick, 1)
            use = QPushButton("Use this client")
            use.setProperty("primary", True)
            use.clicked.connect(lambda: self._done("use"))
            row.addWidget(use)
            v.addLayout(row)
            v.addWidget(self.remember)
        row = QHBoxLayout()
        new = QPushButton(f"New client “{label}”…")
        new.clicked.connect(lambda: self._done("new"))
        skip = QPushButton("Skip")
        skip.clicked.connect(lambda: self._done("skip"))
        row.addWidget(new)
        row.addStretch(1)
        row.addWidget(skip)
        v.addLayout(row)

    def _done(self, choice: str) -> None:
        self.choice = choice
        self.accept()


class PaidDialog(QDialog):
    def __init__(self, number: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Mark as paid")
        v = QVBoxLayout(self)
        v.addWidget(QLabel(f"When was invoice {number} paid?"))
        self.date = QDateEdit(QDate.currentDate())
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("MMM d, yyyy")
        v.addWidget(self.date)
        v.addWidget(buttons(self, "Mark paid"))

    def paid_date(self) -> str:
        return self.date.date().toString("yyyy-MM-dd")


# ---- settings -----------------------------------------------------------------------------------------
class SettingsDialog(QDialog):
    def __init__(self, data: Data, detected_logs_dir: Path | None, version: str, parent: QWidget | None = None,
                 on_check_updates: Callable[[], None] | None = None):
        super().__init__(parent)
        self.data = data
        self.s: Settings = copy.deepcopy(data.settings)
        self.detected = detected_logs_dir
        self.run_setup = False
        self.setWindowTitle(f"Docket Ledger {version} settings")
        self.resize(560, 560)
        v = QVBoxLayout(self)
        tabs = QTabWidget()
        v.addWidget(tabs, 1)
        s = self.s

        # general
        w = QWidget()
        g = QVBoxLayout(w)
        g.addWidget(section("I use Docket Ledger for"))
        self.u_ts = QCheckBox("Timesheets from Docket time logs")
        self.u_inv = QCheckBox("Invoices from Docket time logs")
        self.u_sa = QCheckBox("Standalone invoices (no Docket needed)")
        for cb, val in ((self.u_ts, s.use_docket_timesheets), (self.u_inv, s.use_docket_invoices),
                        (self.u_sa, s.use_standalone)):
            cb.setChecked(val)
            g.addWidget(cb)
        g.addWidget(hint("Ledger only shows what these need. Nothing is deleted when you untick one."))
        g.addWidget(section("Appearance"))
        self.theme = combo([("system", "Match Windows"), ("light", "Light"), ("dark", "Dark")], s.theme)
        g.addWidget(self.theme)
        g.addWidget(section("Updates"))
        self.updates = QCheckBox("Check for updates when Docket Ledger starts")
        self.updates.setChecked(s.check_updates)
        g.addWidget(self.updates)
        g.addWidget(hint("Checking for updates is the only time Docket Ledger goes online."))
        if on_check_updates is not None:
            now = QPushButton("Check now")
            now.clicked.connect(on_check_updates)
            r = QHBoxLayout()
            r.addWidget(now)
            r.addStretch(1)
            g.addLayout(r)
        g.addStretch(1)
        again = QPushButton("Run setup again…")
        again.clicked.connect(self._again)
        r = QHBoxLayout()
        r.addWidget(again)
        r.addStretch(1)
        g.addLayout(r)
        tabs.addTab(w, "General")

        # time logs
        w = QWidget()
        g = QVBoxLayout(w)
        g.addWidget(section("Time logs folder"))
        row = QHBoxLayout()
        self.folder = QLineEdit()
        self.folder.setReadOnly(True)
        change = QPushButton("Change…")
        change.clicked.connect(self._choose_folder)
        self.use_docket = QPushButton("Use Docket's")
        self.use_docket.clicked.connect(self._use_docket)
        row.addWidget(self.folder, 1)
        row.addWidget(change)
        row.addWidget(self.use_docket)
        g.addLayout(row)
        self.folder_hint = hint("")
        g.addWidget(self.folder_hint)
        self._show_folder()
        g.addWidget(section("Timesheet defaults"))
        f = QFormLayout()
        self.time_format = combo(TIME_FORMATS, s.time_format)
        self.clock = combo([("24", "24-hour"), ("12", "12-hour")], s.clock)
        self.seconds = QCheckBox("Show seconds in Start and End")
        self.seconds.setChecked(s.show_seconds)
        self.rounding = combo(ROUNDING, s.rounding)
        self.each_row = QCheckBox("Round each row (otherwise each category's total)")
        self.each_row.setChecked(s.round_each_row)
        self.grand_once = QCheckBox("Combined logs: round the grand total from all the time at once")
        self.grand_once.setChecked(s.round_grand_once)
        self.layout_c = combo([("sections", "A section per log"), ("single", "One table")], s.layout)
        self.cat_summary = QCheckBox("Add a “Time by category” table")
        self.cat_summary.setChecked(s.category_summary)
        cols = QPushButton("Columns…")
        cols.clicked.connect(self._columns)
        f.addRow("Time format", self.time_format)
        f.addRow("Clock", self.clock)
        f.addRow("", self.seconds)
        f.addRow("Rounding", self.rounding)
        f.addRow("", self.each_row)
        f.addRow("", self.grand_once)
        f.addRow("Combined logs", self.layout_c)
        f.addRow("", self.cat_summary)
        f.addRow("Columns", cols)
        g.addLayout(f)
        g.addStretch(1)
        tabs.addTab(w, "Time logs")

        # invoices
        w = QWidget()
        f = QFormLayout(w)
        self.fmt = QComboBox()
        self.fmt.setEditable(True)
        for code, label in NUMBER_FORMATS:
            self.fmt.addItem(label, code)
        i = self.fmt.findData(s.number_format)
        if i >= 0:
            self.fmt.setCurrentIndex(i)
        else:
            self.fmt.setEditText(s.number_format)
        self.fmt.currentTextChanged.connect(self._preview_number)
        f.addRow("Invoice numbers", self.fmt)
        f.addRow("", hint("Or type your own using {YYYY} {YY} {MM} {DD} and a counter {NN} (more Ns = more "
                          "digits). The counter restarts each day, month or year, following the date parts used."))
        self.number_preview = QLabel(objectName="Note")
        f.addRow("Next number", self.number_preview)
        self.next_n = QSpinBox()
        self.next_n.setRange(1, 999999)
        f.addRow("Continue from", self.next_n)
        f.addRow("", hint("Switching from another invoicing tool? Set the next counter value here."))
        self.currency = combo(currency_choices(), s.currency)
        f.addRow("Default currency", self.currency)
        self.terms = QSpinBox()
        self.terms.setRange(0, 365)
        self.terms.setSuffix(" days")
        self.terms.setSpecialValueText("Due on receipt")
        self.terms.setValue(int(s.terms_days))
        f.addRow("Default payment terms", self.terms)
        self.next_n.valueChanged.connect(self._preview_number)
        self._init_next()
        tabs.addTab(w, "Invoices")

        # data
        w = QWidget()
        g = QVBoxLayout(w)
        g.addWidget(section("Your data"))
        g.addWidget(hint("Everything Docket Ledger saves stays on this PC, in this folder. No account, and nothing "
                         "is uploaded. Client details are never sent anywhere, including to AI apps."))
        row = QHBoxLayout()
        df = QLineEdit(str(data.folder))
        df.setReadOnly(True)
        open_btn = QPushButton("Open")
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(data.folder))))
        row.addWidget(df, 1)
        row.addWidget(open_btn)
        g.addLayout(row)
        g.addWidget(section("Backups"))
        g.addWidget(hint("Invoices are business records, and tax rules often require keeping them for years. "
                         "Pick a folder (OneDrive or a USB drive works well) and Ledger keeps a daily zip of its "
                         "data there, the newest 30."))
        row = QHBoxLayout()
        self.backup = QLineEdit(s.backup_dir)
        self.backup.setReadOnly(True)
        self.backup.setPlaceholderText("Off until a folder is chosen")
        pick = QPushButton("Choose…")
        pick.clicked.connect(self._choose_backup)
        off = QPushButton("Turn off")
        off.clicked.connect(lambda: self.backup.setText(""))
        row.addWidget(self.backup, 1)
        row.addWidget(pick)
        row.addWidget(off)
        g.addLayout(row)
        now = QPushButton("Back up now")
        now.clicked.connect(self._backup_now)
        self.backup_status = hint(f"Last backup: {s.last_backup}" if s.last_backup else "")
        r = QHBoxLayout()
        r.addWidget(now)
        r.addWidget(self.backup_status, 1)
        g.addLayout(r)
        g.addStretch(1)
        tabs.addTab(w, "Data")

        v.addWidget(buttons(self))

    # ---- helpers
    def _again(self) -> None:
        self.run_setup = True
        self.accept()

    def _show_folder(self) -> None:
        if self.s.logs_dir:
            self.folder.setText(self.s.logs_dir)
            self.folder_hint.setText("Chosen by hand.")
        elif self.detected:
            self.folder.setText(str(self.detected))
            self.folder_hint.setText("From Docket's settings.")
        else:
            self.folder.setText("")
            self.folder_hint.setText("Docket's time logs folder wasn't found. Choose it with Change…")
        self.use_docket.setEnabled(bool(self.s.logs_dir))

    def _choose_folder(self) -> None:
        start = self.s.logs_dir or (str(self.detected) if self.detected else str(Path.home() / "Documents"))
        path = QFileDialog.getExistingDirectory(self, "Time logs folder", start)
        if path:
            self.s.logs_dir = path
            self._show_folder()

    def _use_docket(self) -> None:
        self.s.logs_dir = ""
        self._show_folder()

    def _columns(self) -> None:
        d = ColumnsDialog(self.s.columns, self, "Default columns")
        if d.exec():
            self.s.columns = d.columns()

    def _fmt(self) -> str:
        data = self.fmt.currentData()
        text = self.fmt.currentText()
        if data and text == self.fmt.itemText(self.fmt.currentIndex()):
            return data
        return text.strip()

    def _init_next(self) -> None:
        n, _ = self.s.next_number(dt.date.today(), self.data.invoices.numbers())
        self.next_n.blockSignals(True)
        self.next_n.setValue(n)
        self.next_n.blockSignals(False)
        self._preview_number()

    def _preview_number(self, *_) -> None:
        fmt = self._fmt()
        if not number_format_ok(fmt):
            self.number_preview.setText("Add a counter, e.g. {NN}")
            return
        period = {"day": "each day", "month": "each month", "year": "each year", "never": "never"}[reset_period(fmt)]
        self.number_preview.setText(f"{format_number(fmt, dt.date.today(), self.next_n.value())}"
                                    f"   (counter restarts: {period})")

    def _choose_backup(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Backup folder", self.backup.text() or str(Path.home()))
        if path:
            self.backup.setText(path)

    def _backup_now(self) -> None:
        if not self.backup.text():
            self.backup_status.setText("Choose a backup folder first.")
            return
        try:
            out = self.data.backup(Path(self.backup.text()))
            self.backup_status.setText(f"Saved {out.name}" if out else "")
        except OSError as e:
            self.backup_status.setText(f"Couldn't back up: {e}")

    def result_settings(self) -> Settings:
        s = self.s
        s.use_docket_timesheets = self.u_ts.isChecked()
        s.use_docket_invoices = self.u_inv.isChecked()
        s.use_standalone = self.u_sa.isChecked()
        if not (s.use_docket_timesheets or s.use_docket_invoices or s.use_standalone):
            s.use_standalone = True
        s.theme = self.theme.currentData()
        s.check_updates = self.updates.isChecked()
        s.time_format = self.time_format.currentData()
        s.clock = self.clock.currentData()
        s.show_seconds = self.seconds.isChecked()
        s.rounding = self.rounding.currentData()
        s.round_each_row = self.each_row.isChecked()
        s.round_grand_once = self.grand_once.isChecked()
        s.layout = self.layout_c.currentData()
        s.category_summary = self.cat_summary.isChecked()
        fmt = self._fmt()
        s.number_format = fmt if number_format_ok(fmt) else DEFAULT_NUMBER_FORMAT
        s.set_next(dt.date.today(), self.next_n.value())
        s.currency = self.currency.currentData()
        s.terms_days = self.terms.value()
        s.backup_dir = self.backup.text()
        s.last_backup = self.data.settings.last_backup
        return s


__all__ = ["ColumnsDialog", "ProfileDialog", "ClientDialog", "ItemsDialog", "ClientMatchDialog", "PaidDialog",
           "SettingsDialog", "TaxTable", "AccentPicker", "NUMBER_FORMATS", "currency_choices"]
