"""Invoice history: every invoice with its status. Open, invoice again, mark paid, delete drafts."""
from __future__ import annotations

import datetime as dt

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..money import dec, fmt_money
from ..store import Data, Invoice
from ..timefmt import fmt_date
from . import theme
from .dialogs import PaidDialog
from .widgets import combo, hint

FILTERS = [("all", "All invoices"), ("draft", "Drafts"), ("unpaid", "Sent, not paid"), ("overdue", "Overdue"),
           ("paid", "Paid")]


def status_text(inv: Invoice) -> tuple[str, str]:
    if inv.status == "paid":
        return "paid", "Paid" + (f" {fmt_date(dt.date.fromisoformat(inv.paid_date))}" if inv.paid_date else "")
    if inv.overdue():
        return "overdue", "Overdue"
    return inv.status, {"draft": "Draft", "sent": "Sent"}[inv.status]


class HistoryPanel(QWidget):
    open_invoice = Signal(object)
    invoice_again = Signal(object)
    changed = Signal()

    def __init__(self, data: Data, parent: QWidget | None = None):
        super().__init__(parent)
        self.data = data
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 6, 4, 4)
        self.filter = combo(FILTERS, "all")
        self.filter.currentIndexChanged.connect(self.refresh)
        v.addWidget(self.filter)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Invoice", "Client", "Total", "Status"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(lambda *_: self._open())
        self.table.itemSelectionChanged.connect(self._update_buttons)
        v.addWidget(self.table, 1)
        grid = QHBoxLayout()
        self.open_btn = QPushButton("Open")
        self.open_btn.clicked.connect(self._open)
        self.again_btn = QPushButton("Invoice again")
        self.again_btn.setToolTip("A new draft with the same client, items and rates")
        self.again_btn.clicked.connect(self._again)
        grid.addWidget(self.open_btn)
        grid.addWidget(self.again_btn)
        v.addLayout(grid)
        grid2 = QHBoxLayout()
        self.paid_btn = QPushButton("Mark paid…")
        self.paid_btn.clicked.connect(self._paid)
        self.delete_btn = QPushButton("Delete draft")
        self.delete_btn.clicked.connect(self._delete)
        grid2.addWidget(self.paid_btn)
        grid2.addWidget(self.delete_btn)
        v.addLayout(grid2)
        self.summary = hint("")
        v.addWidget(self.summary)
        self.refresh()

    def selected(self) -> Invoice | None:
        rows = {i.row() for i in self.table.selectedIndexes()}
        if not rows:
            return None
        item = self.table.item(min(rows), 0)
        return self.data.invoices.invoices.get(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def refresh(self, *_) -> None:
        keep = self.selected()
        f = self.filter.currentData()
        rows = []
        for inv in self.data.invoices.all():
            if inv.sample:
                continue
            key, _ = status_text(inv)
            if f == "draft" and inv.status != "draft":
                continue
            if f == "unpaid" and inv.status != "sent":
                continue
            if f == "overdue" and key != "overdue":
                continue
            if f == "paid" and inv.status != "paid":
                continue
            rows.append(inv)
        self.table.setRowCount(len(rows))
        pal = theme.current
        colours = {"draft": pal["muted"], "sent": pal["accent"], "paid": pal["good"], "overdue": pal["warn"]}
        unpaid = {}
        for i, inv in enumerate(rows):
            key, text = status_text(inv)
            client = self.data.client(inv.client_id)
            name = inv.client_name or (client.display if client else "")
            date = fmt_date(inv.issue) if inv.issue_date else ""
            num = QTableWidgetItem(inv.number or "(draft)")
            num.setData(Qt.ItemDataRole.UserRole, inv.id)
            num.setToolTip(date)
            total = dec(inv.total, None)
            cells = [num, QTableWidgetItem(name), QTableWidgetItem(fmt_money(total, inv.currency) if total is not None
                                                                   else ""), QTableWidgetItem(text)]
            cells[2].setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            cells[3].setForeground(QColor(colours[key]))
            for c, it in enumerate(cells):
                self.table.setItem(i, c, it)
            if inv.status == "sent" and total is not None:
                unpaid[inv.currency] = unpaid.get(inv.currency, 0) + total
            if keep is not None and inv.id == keep.id:
                self.table.selectRow(i)
        if unpaid:
            self.summary.setText("Waiting for payment: " + ", ".join(fmt_money(v, k, code=True)
                                                                     for k, v in unpaid.items()))
        else:
            self.summary.setText("" if rows else "No invoices yet.")
        self._update_buttons()

    def _update_buttons(self) -> None:
        inv = self.selected()
        self.open_btn.setEnabled(inv is not None)
        self.again_btn.setEnabled(inv is not None)
        self.paid_btn.setEnabled(inv is not None and inv.status != "draft")
        self.paid_btn.setText("Mark unpaid" if inv is not None and inv.status == "paid" else "Mark paid…")
        self.delete_btn.setEnabled(inv is not None and inv.status == "draft")

    def _open(self) -> None:
        inv = self.selected()
        if inv is not None:
            self.open_invoice.emit(inv)

    def _again(self) -> None:
        inv = self.selected()
        if inv is not None:
            self.invoice_again.emit(inv)

    def _paid(self) -> None:
        inv = self.selected()
        if inv is None or inv.status == "draft":
            return
        if inv.status == "paid":
            inv.status, inv.paid_date = "sent", ""
        else:
            d = PaidDialog(inv.number, self)
            if not d.exec():
                return
            inv.status, inv.paid_date = "paid", d.paid_date()
        self.data.invoices.save(inv)
        self.refresh()
        self.changed.emit()

    def _delete(self) -> None:
        inv = self.selected()
        if inv is None or inv.status != "draft":
            return
        if QMessageBox.question(self, "Delete draft", "Delete this draft invoice?") == QMessageBox.StandardButton.Yes:
            self.data.invoices.delete(inv)
            self.refresh()
            self.changed.emit()
