"""Invoice mode: client, details, time from Docket logs, items, taxes, notes and status."""
from __future__ import annotations

import copy
import datetime as dt
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QFileDialog, QFormLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QMessageBox, QPlainTextEdit,
                               QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout,
                               QWidget)

from .. import invoicing as inv_mod
from ..model import build_spec
from ..money import dec, fmt_money, fmt_number
from ..pdf import build_invoice_pdf
from ..store import Client, Invoice, SavedItem, new_id
from ..timefmt import ROUNDING, fmt_date
from . import theme
from .dialogs import ClientDialog, ItemsDialog, PaidDialog, currency_choices
from .timesheet_panel import safe_filename
from .widgets import combo, hint, section, set_combo

KIND_CHOICES = [("hours", "Hours"), ("qty", "Quantity"), ("fixed", "Fixed price")]


def qdate(d: dt.date) -> QDate:
    return QDate(d.year, d.month, d.day)


def pydate(q: QDate) -> dt.date:
    return dt.date(q.year(), q.month(), q.day())


class InvoicePanel(QWidget):
    changed = Signal()
    exported = Signal()

    def __init__(self, main, parent: QWidget | None = None):
        super().__init__(parent)
        self.main = main
        self.data = main.data
        self.inv: Invoice = Invoice()
        self.sample_client: Client | None = None
        self._loading = False
        self._skipped_labels: set[str] = set()
        self.save_timer = QTimer(self, singleShot=True, interval=1200, timeout=self._autosave)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        # status line
        top = QHBoxLayout()
        self.status = QLabel(objectName="Status")
        self.number = QLabel(objectName="Big")
        top.addWidget(self.number)
        top.addWidget(self.status)
        top.addStretch(1)
        self.paid_btn = QPushButton("Mark paid…")
        self.paid_btn.clicked.connect(self._mark_paid)
        top.addWidget(self.paid_btn)
        v.addLayout(top)
        self.banner = QLabel(objectName="WarnBox")
        self.banner.setWordWrap(True)
        self.banner.hide()
        v.addWidget(self.banner)

        # client
        v.addWidget(section("Bill to"))
        row = QHBoxLayout()
        self.client = QComboBox()
        self.client.currentIndexChanged.connect(self._client_changed)
        row.addWidget(self.client, 1)
        more = QToolButton(text="⋯", toolTip="Clients")
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(more)
        menu.addAction(QAction("New client…", menu, triggered=lambda: self.new_client()))
        menu.addAction(QAction("Edit this client…", menu, triggered=self.edit_client))
        menu.addSeparator()
        menu.addAction(QAction("Delete this client…", menu, triggered=self.delete_client))
        more.setMenu(menu)
        row.addWidget(more)
        v.addLayout(row)

        # details
        v.addWidget(section("Details"))
        f = QFormLayout()
        self.title = QLineEdit()
        self.title.textEdited.connect(self._edited)
        f.addRow("Title", self.title)
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("MMM d, yyyy")
        self.date.dateChanged.connect(self._date_changed)
        f.addRow("Date", self.date)
        terms_row = QHBoxLayout()
        self.terms = QSpinBox()
        self.terms.setRange(0, 365)
        self.terms.setSuffix(" days")
        self.terms.setSpecialValueText("Due on receipt")
        self.terms.valueChanged.connect(self._terms_changed)
        self.due = QDateEdit()
        self.due.setCalendarPopup(True)
        self.due.setDisplayFormat("MMM d, yyyy")
        self.due.dateChanged.connect(self._edited)
        terms_row.addWidget(self.terms)
        terms_row.addWidget(QLabel("due"))
        terms_row.addWidget(self.due, 1)
        f.addRow("Terms", terms_row)
        self.currency = combo(currency_choices(), "CAD")
        self.currency.currentIndexChanged.connect(self._edited)
        f.addRow("Currency", self.currency)
        v.addLayout(f)

        # time from logs
        self.time_box = QWidget()
        tv = QVBoxLayout(self.time_box)
        tv.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        head.addWidget(section("Time from Docket"), 1)
        edit_time = QPushButton("Edit the time…")
        edit_time.setProperty("link", True)
        edit_time.setToolTip("Open these logs in Timesheet mode to fix or hide rows")
        edit_time.clicked.connect(lambda: self.main.set_mode("timesheet"))
        head.addWidget(edit_time)
        tv.addLayout(head)
        self.billed_warning = QLabel(objectName="WarnBox")
        self.billed_warning.setWordWrap(True)
        self.billed_warning.hide()
        tv.addWidget(self.billed_warning)
        self.time_table = QTableWidget(0, 4)
        self.time_table.setHorizontalHeaderLabels(["Category", "Hours", "Rate", "Amount"])
        self.time_table.verticalHeader().setVisible(False)
        self.time_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.time_table.setMinimumHeight(120)
        self.time_table.itemChanged.connect(self._rate_edited)
        tv.addWidget(self.time_table)
        self.rate_hint = QLabel(objectName="Warn")
        self.rate_hint.setWordWrap(True)
        tv.addWidget(self.rate_hint)
        r = QHBoxLayout()
        self.save_rates = QPushButton("Save these rates to the client")
        self.save_rates.clicked.connect(self._save_rates)
        r.addWidget(self.save_rates)
        r.addStretch(1)
        tv.addLayout(r)
        f = QFormLayout()
        self.rounding = combo(ROUNDING, "off")
        self.rounding.currentIndexChanged.connect(self._edited)
        self.each_row = QCheckBox("Round each row (otherwise each category's total)")
        self.each_row.toggled.connect(self._edited)
        self.attach = QCheckBox("Attach the timesheet after the invoice")
        self.attach.toggled.connect(self._edited)
        f.addRow("Rounding", self.rounding)
        f.addRow("", self.each_row)
        f.addRow("", self.attach)
        tv.addLayout(f)
        v.addWidget(self.time_box)

        # items
        head = QHBoxLayout()
        head.addWidget(section("Items"), 1)
        v.addLayout(head)
        self.items = QTableWidget(0, 6)
        self.items.setHorizontalHeaderLabels(["Type", "Description", "Qty / hours", "Unit", "Price / rate", "Amount"])
        self.items.verticalHeader().setVisible(False)
        self.items.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        hh = self.items.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.items.setMinimumHeight(140)
        self.items.itemChanged.connect(self._item_edited)
        v.addWidget(self.items)
        row = QHBoxLayout()
        add = QPushButton("+ Item")
        add.clicked.connect(lambda: self.add_line({"kind": "hours", "description": "", "qty": "", "unit": "h",
                                                   "price": ""}, edit=True))
        rem = QPushButton("Remove")
        rem.clicked.connect(self._remove_lines)
        up = QPushButton("↑")
        up.clicked.connect(lambda: self._move_line(-1))
        down = QPushButton("↓")
        down.clicked.connect(lambda: self._move_line(1))
        self.saved_btn = QToolButton(text="Saved items ▾")
        self.saved_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.saved_menu = QMenu(self.saved_btn)
        self.saved_menu.aboutToShow.connect(self._fill_saved_menu)
        self.saved_btn.setMenu(self.saved_menu)
        imp = QPushButton("Import hours…")
        imp.setToolTip("Add hours from another time tracker's CSV (date, description, hours, category)")
        imp.clicked.connect(self._import_csv)
        for b in (add, rem, up, down):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(self.saved_btn)
        row.addWidget(imp)
        v.addLayout(row)

        # adjustments
        v.addWidget(section("Discount and taxes"))
        row = QHBoxLayout()
        self.discount_kind = combo([("none", "No discount"), ("percent", "Discount %"), ("amount", "Discount amount")],
                                   "none")
        self.discount_kind.currentIndexChanged.connect(self._edited)
        self.discount_value = QLineEdit()
        self.discount_value.setPlaceholderText("0")
        self.discount_value.setFixedWidth(90)
        self.discount_value.textEdited.connect(self._edited)
        row.addWidget(self.discount_kind)
        row.addWidget(self.discount_value)
        row.addStretch(1)
        v.addLayout(row)
        self.tax_row = QHBoxLayout()
        v.addLayout(self.tax_row)
        self.tax_boxes: list[tuple[str, QCheckBox]] = []

        v.addWidget(section("Notes"))
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("A note for this invoice (printed). Payment instructions come from your "
                                      "business profile.")
        self.notes.setFixedHeight(60)
        self.notes.textChanged.connect(self._edited)
        v.addWidget(self.notes)
        self.totals_label = QLabel(objectName="Note")
        self.totals_label.setWordWrap(True)
        v.addWidget(self.totals_label)

        self.reload_clients()
        self.new_invoice()

    # =========================================================== the invoice
    def client_obj(self) -> Client | None:
        if self.inv.sample:
            return self.sample_client
        return self.data.client(self.inv.client_id)

    def new_invoice(self, from_logs: list[str] | None = None) -> None:
        s = self.data.settings
        today = dt.date.today()
        inv = Invoice(issue_date=today.isoformat(), terms_days=s.terms_days,
                      due_date=(today + dt.timedelta(days=s.terms_days)).isoformat(), currency=s.currency,
                      profile=self.main.profile().name, rounding=s.rounding, round_each_row=s.round_each_row)
        inv.taxes = inv_mod.taxes_for_client(self.main.profile(), None)
        self.sample_client = None
        self.load(inv)
        if from_logs:
            self.set_logs(from_logs)

    def again(self, src: Invoice) -> None:
        """A new draft copying the client, items, rates and taxes of an earlier invoice."""
        today = dt.date.today()
        inv = Invoice.from_dict(copy.deepcopy(src.to_dict()))
        inv.id, inv.number, inv.status = new_id(), "", "draft"
        inv.created = inv.updated = inv.paid_date = inv.total = inv.subtotal = inv.pdf_path = ""
        inv.client_snapshot = {}
        inv.log_refs = []
        inv.issue_date = today.isoformat()
        inv.due_date = (today + dt.timedelta(days=inv.terms_days)).isoformat()
        self.sample_client = None
        self.load(inv)
        self.main.tick_logs([])
        self._edited()

    def load_sample(self) -> None:
        today = dt.date.today()
        self.sample_client = Client(id="sample", label="Sample", name="Sample Client Ltd.",
                                    bill_to="Attn: Accounts\n100 Example Avenue\nSampletown",
                                    currency=self.data.settings.currency, terms_days=30,
                                    rates={"Design": "85", "Revisions": "60"})
        inv = Invoice(issue_date=today.isoformat(), terms_days=30,
                      due_date=(today + dt.timedelta(days=30)).isoformat(), currency=self.data.settings.currency,
                      client_id="sample", sample=True, profile=self.main.profile().name,
                      lines=[{"kind": "hours", "description": "Design work", "category": "Design", "qty": "4.5",
                              "unit": "h", "price": "85"},
                             {"kind": "qty", "description": "Printed proofs", "qty": "3", "unit": "proofs",
                              "price": "25"},
                             {"kind": "fixed", "description": "Project setup", "price": "150"}],
                      notes="This is a made-up sample. Nothing on it is saved.",
                      taxes=[{"id": "sample", "name": "Tax", "rate": "5", "on": True}])
        self.load(inv)
        self.main.tick_logs([])

    def load(self, inv: Invoice) -> None:
        self.save_now()
        self.inv = inv
        self._loading = True
        self.reload_clients()
        self.client.setCurrentIndex(max(0, self.client.findData(inv.client_id)))
        self.title.setText(inv.title)
        self.date.setDate(qdate(inv.issue))
        self.terms.setValue(int(inv.terms_days))
        self.due.setDate(qdate(inv.due or inv.issue))
        set_combo(self.currency, inv.currency)
        set_combo(self.rounding, inv.rounding)
        self.each_row.setChecked(inv.round_each_row)
        self.attach.setChecked(inv.attach_timesheet)
        set_combo(self.discount_kind, inv.discount_kind)
        self.discount_value.setText(inv.discount_value)
        self.notes.setPlainText(inv.notes)
        self._fill_items()
        self._fill_taxes()
        self._loading = False
        self._update_status()
        self.main.on_invoice_loaded(inv)
        self.changed.emit()

    def open_invoice(self, inv: Invoice) -> None:
        self.sample_client = None
        self.load(Invoice.from_dict(copy.deepcopy(inv.to_dict())))
        present = [r.get("key") for r in inv.log_refs if r.get("key") in self.main.logs]
        self.main.tick_logs(present)

    # =========================================================== logs
    def set_logs(self, keys: list[str]) -> None:
        if self.inv.status != "draft" or self.inv.sample:
            return
        logs = self.main.logs
        keys = [k for k in keys if k in logs]
        missing = [r for r in self.inv.log_refs if r.get("key") not in logs]
        self.inv.log_refs = missing + [{"key": k, "path": str(logs[k].path or ""), "title": logs[k].title}
                                       for k in sorted(keys, key=lambda k: logs[k].sort_time)]
        for k in keys:
            self.main.ensure_edits(k)
        if keys and not self.inv.client_id:
            labels = {logs[k].client for k in keys if logs[k].client}
            if len(labels) == 1:
                label = next(iter(labels))
                client = self.main.match_client(label, ask=label not in self._skipped_labels)
                if client is None:
                    self._skipped_labels.add(label)
                else:
                    self.reload_clients()
                    self.apply_client(client.id)
        self._edited()

    def entries(self):
        logs = self.main.logs
        present = [(logs[r["key"]], self.main.ensure_edits(r["key"])) for r in self.inv.log_refs
                   if r.get("key") in logs]
        missing = [r for r in self.inv.log_refs if r.get("key") not in logs and r.get("categories")]
        return present, missing

    # =========================================================== clients
    def reload_clients(self) -> None:
        keep = self.inv.client_id if hasattr(self, "inv") else ""
        was = self._loading
        self._loading = True
        self.client.clear()
        self.client.addItem("Choose a client…", "")
        if self.sample_client is not None:
            self.client.addItem(self.sample_client.display, self.sample_client.id)
        for c in self.data.clients:
            self.client.addItem(c.display + (f"  ({c.label})" if c.label and c.name and c.label != c.name else ""),
                                c.id)
        self.client.setCurrentIndex(max(0, self.client.findData(keep)))
        self._loading = was

    def _client_changed(self, *_) -> None:
        if self._loading:
            return
        self.apply_client(self.client.currentData() or "")

    def apply_client(self, cid: str) -> None:
        """Puts a client on the invoice: its currency, terms and taxes come with it (drafts only)."""
        self.inv.client_id = cid
        self.client.blockSignals(True)
        self.client.setCurrentIndex(max(0, self.client.findData(cid)))
        self.client.blockSignals(False)
        c = self.client_obj()
        if c is not None and self.inv.status == "draft":
            self._loading = True
            set_combo(self.currency, c.currency)
            self.terms.setValue(int(c.terms_days))
            self.due.setDate(self.date.date().addDays(int(c.terms_days)))
            self._loading = False
            self.inv.taxes = inv_mod.taxes_for_client(self.main.profile(), c)
            self._fill_taxes()
        self._edited()

    def new_client(self, label: str = "") -> Client | None:
        known = self.main.known_categories()
        d = ClientDialog(self.data, None, known, self.main.profile(), self, label=label)
        if not d.exec():
            return None
        c = d.result_client()
        self.data.upsert_client(c)
        self.main.clients_changed()
        if not self.inv.sample:
            self.reload_clients()
            self.apply_client(c.id)
        return c

    def edit_client(self) -> None:
        c = self.data.client(self.inv.client_id)
        if c is None:
            self.new_client()
            return
        d = ClientDialog(self.data, c, self.main.known_categories(), self.main.profile(), self)
        if d.exec():
            self.data.upsert_client(d.result_client())
            self.main.clients_changed()
            self.reload_clients()
            self._edited()

    def delete_client(self) -> None:
        c = self.data.client(self.inv.client_id)
        if c is None:
            return
        used = [i.number for i in self.data.invoices.all() if i.client_id == c.id and i.number]
        msg = f"Delete the client “{c.display}”?"
        if used:
            msg += f"\n\nInvoices already sent keep the details printed on them ({len(used)})."
        if QMessageBox.question(self, "Delete client", msg) == QMessageBox.StandardButton.Yes:
            self.data.delete_client(c.id)
            self.inv.client_id = ""
            self.main.clients_changed()
            self.reload_clients()
            self._edited()

    # =========================================================== editing
    def _edited(self, *_) -> None:
        if self._loading:
            return
        inv = self.inv
        inv.title = self.title.text().strip() or "Invoice"
        inv.issue_date = pydate(self.date.date()).isoformat()
        inv.terms_days = self.terms.value()
        inv.due_date = pydate(self.due.date()).isoformat()
        inv.currency = self.currency.currentData()
        inv.rounding = self.rounding.currentData()
        inv.round_each_row = self.each_row.isChecked()
        inv.attach_timesheet = self.attach.isChecked()
        inv.discount_kind = self.discount_kind.currentData()
        inv.discount_value = self.discount_value.text().strip()
        inv.notes = self.notes.toPlainText()
        inv.taxes = [dict(t, on=cb.isChecked()) for t, (_, cb) in zip(inv.taxes, self.tax_boxes)] \
            if len(self.tax_boxes) == len(inv.taxes) else inv.taxes
        self.each_row.setVisible(inv.rounding != "off")
        self.discount_value.setEnabled(inv.discount_kind != "none")
        self.save_timer.start()
        self.changed.emit()

    def _date_changed(self, *_) -> None:
        if self._loading:
            return
        self._loading = True
        self.due.setDate(self.date.date().addDays(self.terms.value()))
        self._loading = False
        self._edited()

    def _terms_changed(self, *_) -> None:
        if self._loading:
            return
        self._loading = True
        self.due.setDate(self.date.date().addDays(self.terms.value()))
        self._loading = False
        self._edited()

    def profile_changed(self) -> None:
        if self.inv.sample:
            return
        self.inv.profile = self.main.profile().name
        self.inv.taxes = inv_mod.taxes_for_client(self.main.profile(), self.client_obj(), self.inv.taxes)
        self._fill_taxes()
        self._edited()

    def _fill_taxes(self) -> None:
        while self.tax_row.count():
            w = self.tax_row.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.tax_boxes = []
        if not self.inv.taxes:
            self.tax_row.addWidget(hint("No taxes set up. Add them in your business profile (Taxes tab)."))
            return
        for t in self.inv.taxes:
            cb = QCheckBox(f"{t.get('name')} ({t.get('rate')}%)")
            cb.setChecked(bool(t.get("on")))
            cb.toggled.connect(self._edited)
            self.tax_row.addWidget(cb)
            self.tax_boxes.append((t.get("id", ""), cb))
        self.tax_row.addStretch(1)

    # ---- item lines
    def _fill_items(self) -> None:
        was = self._loading
        self._loading = True
        self.items.setRowCount(0)
        for d in self.inv.lines:
            self._append_row(d)
        self._loading = was

    def _append_row(self, d: dict) -> None:
        r = self.items.rowCount()
        self.items.insertRow(r)
        kind = combo(KIND_CHOICES, d.get("kind", "hours"))
        kind.currentIndexChanged.connect(lambda _i, w=kind: self._kind_changed(w))
        self.items.setCellWidget(r, 0, kind)
        vals = [d.get("description", ""), d.get("qty", ""), d.get("unit", ""), d.get("price", "")]
        for c, val in enumerate(vals, start=1):
            self.items.setItem(r, c, QTableWidgetItem(str(val)))
        amount = QTableWidgetItem("")
        amount.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        amount.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.items.setItem(r, 5, amount)
        self._style_row(r)

    def _style_row(self, r: int) -> None:
        kind_w = self.items.cellWidget(r, 0)
        kind = kind_w.currentData() if kind_w else "hours"
        for c in (2, 3):
            it = self.items.item(r, c)
            if it is None:
                continue
            fixed = kind == "fixed" or (c == 3 and kind == "hours")
            it.setFlags((Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable) if fixed else
                        (Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable))
            it.setForeground(QColor(theme.current["muted"] if fixed else theme.current["text"]))
            if c == 3 and kind == "hours":
                it.setText("h")
            if kind == "fixed":
                it.setText("")
        price = self.items.item(r, 4)
        if price is not None:
            price.setToolTip("The total for this item" if kind == "fixed" else
                             ("Rate per hour" if kind == "hours" else "Price per unit"))

    def _kind_changed(self, w: QComboBox) -> None:
        for r in range(self.items.rowCount()):
            if self.items.cellWidget(r, 0) is w:
                self._loading = True
                self._style_row(r)
                self._loading = False
        self._read_items()

    def _item_edited(self, *_) -> None:
        if not self._loading:
            self._read_items()

    def _read_items(self) -> None:
        lines = []
        for r in range(self.items.rowCount()):
            kind_w = self.items.cellWidget(r, 0)
            old = self.inv.lines[r] if r < len(self.inv.lines) else {}

            def txt(c: int) -> str:
                it = self.items.item(r, c)
                return it.text().strip() if it else ""
            lines.append({"kind": kind_w.currentData() if kind_w else "hours", "description": txt(1),
                          "qty": txt(2), "unit": txt(3), "price": txt(4), "category": old.get("category", ""),
                          "detail": old.get("detail", "")})
        self.inv.lines = lines
        self._edited()

    def add_line(self, d: dict, edit: bool = False) -> None:
        self.inv.lines.append(d)
        self._loading = True
        self._append_row(d)
        self._loading = False
        if edit:
            r = self.items.rowCount() - 1
            self.items.setCurrentCell(r, 1)
            self.items.editItem(self.items.item(r, 1))
        self._edited()

    def _remove_lines(self) -> None:
        rows = sorted({i.row() for i in self.items.selectedIndexes()}, reverse=True)
        for r in rows:
            if r < len(self.inv.lines):
                del self.inv.lines[r]
        self._fill_items()
        self._edited()

    def _move_line(self, delta: int) -> None:
        rows = sorted({i.row() for i in self.items.selectedIndexes()})
        if len(rows) != 1:
            return
        i, j = rows[0], rows[0] + delta
        if 0 <= j < len(self.inv.lines):
            self.inv.lines[i], self.inv.lines[j] = self.inv.lines[j], self.inv.lines[i]
            self._fill_items()
            self.items.selectRow(j)
            self._edited()

    def _fill_saved_menu(self) -> None:
        self.saved_menu.clear()
        for it in self.data.items:
            label = it.description + (f"  — {it.price}" if it.price else "")
            self.saved_menu.addAction(QAction(label, self.saved_menu,
                                              triggered=lambda _=False, i=it: self._use_saved(i)))
        if self.data.items:
            self.saved_menu.addSeparator()
        sel = sorted({i.row() for i in self.items.selectedIndexes()})
        if len(sel) == 1 and sel[0] < len(self.inv.lines):
            self.saved_menu.addAction(QAction("Save the selected item", self.saved_menu,
                                              triggered=lambda: self._save_as_item(sel[0])))
        self.saved_menu.addAction(QAction("Manage saved items…", self.saved_menu, triggered=self._manage_items))

    def _use_saved(self, it: SavedItem) -> None:
        price = it.price
        c = self.client_obj()
        if it.kind == "hours" and it.category and c is not None and c.rate_for(it.category):
            price = c.rate_for(it.category)
        self.add_line({"kind": it.kind, "description": it.description, "category": it.category,
                       "qty": "1" if it.kind != "fixed" else "", "unit": "h" if it.kind == "hours" else it.unit,
                       "price": price})

    def _save_as_item(self, r: int) -> None:
        d = self.inv.lines[r]
        if not d.get("description"):
            return
        self.data.items.append(SavedItem(description=d["description"], kind=d.get("kind", "hours"),
                                         unit=d.get("unit", ""), price=d.get("price", ""),
                                         category=d.get("category", "")))
        self.data.save_items()
        self.main.status(f"Saved “{d['description']}” to your items")

    def _manage_items(self) -> None:
        ItemsDialog(self.data, self).exec()

    def _import_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import hours", str(Path.home() / "Documents"), "CSV (*.csv)")
        if not path:
            return
        try:
            lines = inv_mod.import_hours_csv(Path(path))
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Import hours", f"Couldn't read that file.\n{e}")
            return
        c = self.client_obj()
        for d in lines:
            if c is not None:
                d["price"] = c.rate_for(d.get("category", ""))
            self.inv.lines.append(d)
        self._fill_items()
        self._edited()
        self.main.status(f"Added {len(lines)} line{'s' if len(lines) != 1 else ''} from {Path(path).name}")

    # ---- rates for log categories
    def _rate_edited(self, item: QTableWidgetItem) -> None:
        if self._loading or item.column() != 2:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        text = item.text().strip()
        if text:
            self.inv.category_rates[key] = text
        else:
            self.inv.category_rates.pop(key, None)
        self._edited()

    def _save_rates(self) -> None:
        c = self.data.client(self.inv.client_id)
        if c is None:
            return
        present, missing = self.entries()
        labels = {ct.key: ct.label for ct in inv_mod.category_times(present, missing, self.inv)}
        for key, rate in self.inv.category_rates.items():
            name = labels.get(key) or key
            existing = next((n for n in c.rates if n.lower() == key), None)
            c.rates[existing or (name if key else "General")] = rate
        self.data.upsert_client(c)
        self.main.clients_changed()
        self.inv.category_rates = {}
        self._edited()
        self.main.status(f"Saved the rates to {c.display}")

    # =========================================================== building
    def has_document(self) -> bool:
        return True

    def empty_message(self) -> str:
        return ""

    def _number_text(self) -> str:
        if self.inv.number:
            return self.inv.number
        if self.inv.sample:
            return "SAMPLE-01"
        return self.data.settings.next_number(self.inv.issue, self.data.invoices.numbers())[1]

    def compute(self):
        """(lines, attachment spec) for the current invoice."""
        present, missing = self.entries()
        client = self.client_obj()
        times = inv_mod.category_times(present, missing, self.inv)
        detail = inv_mod.logs_detail(present, missing) if (present or missing) else ""
        lines = inv_mod.log_lines(times, self.inv, client, detail) + inv_mod.manual_lines(self.inv)
        attachment = None
        if self.inv.attach_timesheet and present:
            opts = self.main.opts.copy()
            opts.rounding, opts.round_each_row, opts.round_grand_once = \
                self.inv.rounding, self.inv.round_each_row, True
            first = present[0][0]
            title = first.title if len(present) == 1 else "Timesheet"
            attachment = build_spec(present, title, "", opts)
        return lines, attachment, times

    def build(self, profile):
        lines, attachment, times = self.compute()
        client = self.client_obj()
        spec = inv_mod.build_invoice_spec(self.inv, client, profile, lines, self._number_text(), attachment)
        result = build_invoice_pdf(spec, profile, self.data.image_path(profile.logo),
                                   self.data.image_path(profile.watermark), self.main.author(profile),
                                   stamp="SAMPLE" if self.inv.sample else "")
        self._show_time_table(times, client)
        self._show_totals(spec)
        self.last_spec = spec
        return result

    def _show_time_table(self, times, client) -> None:
        present, missing = self.entries()
        self.time_box.setVisible(bool(present or missing))
        self._loading = True
        self.time_table.setRowCount(len(times))
        unpriced = []
        for i, ct in enumerate(times):
            rate = inv_mod.rate_for(self.inv, client, ct.key, ct.label)
            price = dec(rate, None)
            hours = inv_mod.hours_from_seconds(ct.seconds)
            cells = [QTableWidgetItem(ct.label), QTableWidgetItem(fmt_number(hours)), QTableWidgetItem(rate),
                     QTableWidgetItem(fmt_money(hours * price, self.inv.currency) if price is not None else "—")]
            for c, it in enumerate(cells):
                if c != 2:
                    it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                if c in (1, 2, 3):
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.time_table.setItem(i, c, it)
            cells[2].setData(Qt.ItemDataRole.UserRole, ct.key)
            if price is None:
                cells[2].setBackground(QColor(theme.current["edited"]))
                cells[2].setToolTip("No rate for this category yet. Type one here.")
                unpriced.append(ct.label)
        self._loading = False
        self.rate_hint.setText(f"No rate yet for {', '.join(unpriced)}. Type a rate in the table."
                               if unpriced else "")
        self.rate_hint.setVisible(bool(unpriced))
        self.save_rates.setVisible(bool(self.inv.category_rates) and self.data.client(self.inv.client_id) is not None
                                   and self.inv.status == "draft")
        # already billed?
        billed = self.data.invoices.invoiced_logs(self.inv.id)
        dup = [f"{r.get('title') or r.get('key')} (invoice {', '.join(billed[r['key']])})"
               for r in self.inv.log_refs if r.get("key") in billed]
        self.billed_warning.setText("Already billed: " + "; ".join(dup) if dup else "")
        self.billed_warning.setVisible(bool(dup))

    def _show_totals(self, spec) -> None:
        t = spec.totals
        for r in range(self.items.rowCount()):
            it = self.items.item(r, 5)
            if it is None or r >= len(self.inv.lines):
                continue
            lines = inv_mod.manual_lines(Invoice(lines=[self.inv.lines[r]]))
            self._loading = True
            it.setText(fmt_money(lines[0].amount, self.inv.currency) if lines and lines[0].price is not None else "")
            self._loading = False
        text = f"Subtotal {fmt_money(t.subtotal, spec.currency)}"
        if t.discount:
            text += f" · discount {fmt_money(t.discount, spec.currency)}"
        for tax in t.taxes:
            text += f" · {tax.name} {fmt_money(tax.amount, spec.currency)}"
        text += f" · Total {fmt_money(t.total, spec.currency, code=True)}"
        self.totals_label.setText(text)

    def _update_status(self) -> None:
        inv = self.inv
        if inv.sample:
            self.number.setText("Sample invoice")
            self.status.setText("Made-up example, nothing is saved")
            self.status.setProperty("status", "draft")
        elif inv.status == "draft":
            self.number.setText("New invoice" if not inv.number else f"Invoice {inv.number}")
            self.status.setText("Draft · number given when exported")
            self.status.setProperty("status", "draft")
        elif inv.status == "paid":
            self.number.setText(f"Invoice {inv.number}")
            when = fmt_date(dt.date.fromisoformat(inv.paid_date)) if inv.paid_date else ""
            self.status.setText(f"Paid {when}".strip())
            self.status.setProperty("status", "paid")
        else:
            self.number.setText(f"Invoice {inv.number}")
            self.status.setText("Overdue" if inv.overdue() else "Sent")
            self.status.setProperty("status", "overdue" if inv.overdue() else "sent")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.paid_btn.setVisible(inv.status != "draft" and not inv.sample)
        self.paid_btn.setText("Mark unpaid" if inv.status == "paid" else "Mark paid…")
        if inv.status != "draft" and not inv.sample:
            self.banner.setText("This invoice has been exported. You can still correct it and export again; it "
                                "keeps its number. Its time logs stay as they were billed.")
            self.banner.show()
        else:
            self.banner.hide()

    def _mark_paid(self) -> None:
        inv = self.inv
        if inv.status == "paid":
            inv.status, inv.paid_date = "sent", ""
        else:
            d = PaidDialog(inv.number, self)
            if not d.exec():
                return
            inv.status, inv.paid_date = "paid", d.paid_date()
        self.data.invoices.save(inv)
        self._update_status()
        self.exported.emit()
        self.changed.emit()

    # =========================================================== saving and exporting
    def _has_content(self) -> bool:
        i = self.inv
        return bool(i.client_id or i.lines or i.log_refs or i.notes.strip())

    def _autosave(self) -> None:
        if not self.inv.sample and self._has_content():
            self.data.invoices.save(self.inv)
            self.main.history_changed()

    def save_now(self) -> None:
        if self.save_timer.isActive():
            self.save_timer.stop()
            self._autosave()

    def default_name(self, number: str) -> str:
        c = self.client_obj()
        who = f"_{safe_filename(c.label or c.name)}" if c else ""
        return f"Invoice_{safe_filename(number)}{who}.pdf"

    def export(self) -> None:
        inv = self.inv
        lines, attachment, _ = self.compute()
        totals = inv_mod.totals(inv, lines)
        if totals.unpriced:
            if QMessageBox.question(self, "Export invoice",
                                    f"These have no rate yet, so they're $0 on the invoice:\n"
                                    f"{', '.join(totals.unpriced)}\n\nExport anyway?") != QMessageBox.StandardButton.Yes:
                return
        billed = self.data.invoices.invoiced_logs(inv.id)
        dup = [r.get("title") or r.get("key") for r in inv.log_refs if r.get("key") in billed]
        if dup and inv.status == "draft":
            if QMessageBox.question(self, "Already billed",
                                    "These logs are already on another invoice:\n" + "\n".join(dup) +
                                    "\n\nBill them again?") != QMessageBox.StandardButton.Yes:
                return
        if not inv.client_id and not inv.sample:
            if QMessageBox.question(self, "Export invoice", "This invoice has no client. Export anyway?") \
                    != QMessageBox.StandardButton.Yes:
                return
        number = self._number_text()
        path = self.main.ask_pdf_path(self.default_name(number))
        if path is None:
            return
        profile = self.main.profile()
        client = self.client_obj()
        before = Invoice.from_dict(copy.deepcopy(inv.to_dict()))
        n = None
        if not inv.sample and not inv.number:
            n, number = self.data.settings.next_number(inv.issue, self.data.invoices.numbers())
            inv.number = number
        if inv.status == "draft" and not inv.sample:
            inv.status = "sent"
            inv.client_snapshot = {"name": client.name or client.label, "label": client.label,
                                   "bill_to": client.bill_to, "email": client.email} if client else {}
            present, missing = self.entries()
            opts = inv_mod.rounding_options(inv)
            inv.log_refs = missing + [inv_mod.ref_for(lg, ed, opts) for lg, ed in present]
        inv.profile = profile.name
        inv.subtotal, inv.total = str(totals.subtotal), str(totals.total)
        spec = inv_mod.build_invoice_spec(inv, client, profile, lines, number, attachment)
        try:
            result = build_invoice_pdf(spec, profile, self.data.image_path(profile.logo),
                                       self.data.image_path(profile.watermark), self.main.author(profile),
                                       stamp="SAMPLE" if inv.sample else "")
            path.write_bytes(result.data)
        except Exception as e:      # noqa: BLE001
            self.inv = before
            QMessageBox.warning(self, "Export invoice", f"Couldn't save the PDF. Is it open in another app?\n{e}")
            return
        if n is not None:
            self.data.settings.commit_number(inv.issue, n)
            self.data.save_settings()
        inv.pdf_path = str(path)
        self.last_spec = spec
        if not inv.sample:
            self.data.invoices.save(inv)
        self._update_status()
        self.main.after_export(path)
        self.exported.emit()
        self.changed.emit()

    def copy_email(self) -> None:
        lines, attachment, _ = self.compute()
        spec = inv_mod.build_invoice_spec(self.inv, self.client_obj(), self.main.profile(), lines,
                                          self._number_text(), None)
        QGuiApplication.clipboard().setText(inv_mod.email_text(spec, self.main.profile().contact))
        self.main.status("Email text copied. Paste it into your email app and attach the PDF.")

