"""First-run setup: what Ledger is for, your business, invoicing basics, look, your data, ready."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from PySide6.QtCore import QLocale, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPlainTextEdit, QPushButton, QRadioButton, QSpinBox, QStackedWidget,
                               QVBoxLayout, QWidget, QFileDialog)

from .. import docket_link
from ..money import CURRENCIES
from ..store import Data, format_number, number_format_ok, DEFAULT_NUMBER_FORMAT
from .dialogs import NUMBER_FORMATS, AccentPicker, TaxTable, currency_choices
from .layout_designer import LayoutDesigner
from .widgets import ImagePicker, combo, hint, section

DOCKET_RELEASES = "https://github.com/poplarponderosa-code/Docket/releases/latest"


def locale_currency() -> str:
    try:
        code = QLocale.system().currencySymbol(QLocale.CurrencySymbolFormat.CurrencyIsoCode)
    except Exception:      # noqa: BLE001
        code = ""
    return code if code in CURRENCIES else "CAD"


def locale_page_size() -> str:
    try:
        country = QLocale.system().territory()
        letter = {QLocale.Country.UnitedStates, QLocale.Country.Canada, QLocale.Country.Mexico,
                  QLocale.Country.Philippines, QLocale.Country.Chile, QLocale.Country.Colombia}
        return "letter" if country in letter else "a4"
    except Exception:      # noqa: BLE001
        return "letter"


class SetupWizard(QDialog):
    PAGES = ["uses", "business", "invoicing", "look", "data", "ready"]

    def __init__(self, data: Data, parent: QWidget | None = None, first_run: bool = True):
        super().__init__(parent)
        self.data = data
        self.first_run = first_run
        self.next_action = ""                 # invoice | log | sample | ""
        s = data.settings
        self.profile = data.profile()
        self.setWindowTitle("Set up Docket Ledger")
        self.resize(620, 640)
        v = QVBoxLayout(self)
        self.stack = QStackedWidget()
        v.addWidget(self.stack, 1)

        # 1. uses
        page, lay = self._page("What will you use Docket Ledger for?", "Tick any. Ledger only shows what you need, "
                                                                     "and you can change this in Settings.")
        self.u_ts = QCheckBox("Timesheets from Docket time logs")
        self.u_inv = QCheckBox("Invoices from Docket time logs")
        self.u_sa = QCheckBox("Standalone invoices (no Docket needed)")
        installed = docket_link.docket_installed()
        self.u_ts.setChecked(s.use_docket_timesheets if not first_run else installed)
        self.u_inv.setChecked(s.use_docket_invoices if not first_run else installed)
        self.u_sa.setChecked(s.use_standalone if not first_run else not installed)
        for cb in (self.u_ts, self.u_inv, self.u_sa):
            cb.toggled.connect(self._uses_changed)
            lay.addWidget(cb)
        if installed:
            folder = docket_link.logs_dir()
            lay.addWidget(hint(f"Docket found: time logs in {folder}" if folder else "Docket found."))
        else:
            row = QHBoxLayout()
            row.addWidget(hint("Docket isn't installed on this PC. It's a free list app with a checklist timer "
                               "that makes the time logs."))
            get = QPushButton("Get Docket")
            get.setProperty("link", True)
            get.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(DOCKET_RELEASES)))
            row.addWidget(get)
            lay.addLayout(row)
        lay.addStretch(1)

        # 2. business
        page, lay = self._page("Your business", "Shown at the top of your timesheets and invoices. You can skip "
                                                "this and fill it in later.")
        f = QFormLayout()
        self.contact = QPlainTextEdit(self.profile.contact)
        self.contact.setPlaceholderText("Business name\nAddress\nEmail · Phone")
        self.contact.setFixedHeight(96)
        f.addRow("Your details", self.contact)
        self.logo = ImagePicker(data, self.profile.logo)
        f.addRow("Logo", self.logo)
        self.accent = AccentPicker(self.profile.accent, data.image_path(self.profile.logo), lambda: None)
        self.logo.changed.connect(lambda: self.accent.refresh(data.image_path(self.logo.name)))
        f.addRow("Header colour", self.accent)
        lay.addLayout(f)
        lay.addWidget(section("Starting layout"))
        self.designer = LayoutDesigner(self.profile.layout, self.profile.preset)
        self.designer.canvas.setMinimumSize(220, 250)
        lay.addWidget(self.designer, 1)

        # 3. invoicing basics
        page, lay = self._page("Invoicing basics", "Defaults for new clients and invoices. Every one can be changed "
                                                   "later.")
        f = QFormLayout()
        self.currency = combo(currency_choices(), s.currency if not first_run else locale_currency())
        f.addRow("Currency", self.currency)
        self.terms = QSpinBox()
        self.terms.setRange(0, 365)
        self.terms.setSuffix(" days")
        self.terms.setSpecialValueText("Due on receipt")
        self.terms.setValue(int(s.terms_days))
        f.addRow("Payment terms", self.terms)
        self.tax_number = QLineEdit(self.profile.tax_number)
        self.tax_number.setPlaceholderText("Optional, e.g. GST/HST no.")
        f.addRow("Tax or business no.", self.tax_number)
        self.fmt = QComboBox()
        self.fmt.setEditable(True)
        for code, label in NUMBER_FORMATS:
            self.fmt.addItem(label, code)
        i = self.fmt.findData(s.number_format)
        if i >= 0:
            self.fmt.setCurrentIndex(i)
        else:
            self.fmt.setEditText(s.number_format)
        self.fmt.currentTextChanged.connect(self._number_preview)
        f.addRow("Invoice numbers", self.fmt)
        self.number_label = QLabel(objectName="Note")
        f.addRow("", self.number_label)
        self.continuing = QCheckBox("Continuing from another invoicing tool")
        self.next_n = QSpinBox()
        self.next_n.setRange(1, 999999)
        self.next_n.setEnabled(False)
        self.continuing.toggled.connect(self.next_n.setEnabled)
        self.continuing.toggled.connect(self._number_preview)
        self.next_n.valueChanged.connect(self._number_preview)
        row = QHBoxLayout()
        row.addWidget(self.continuing)
        row.addWidget(QLabel("next number"))
        row.addWidget(self.next_n)
        row.addStretch(1)
        f.addRow("", row)
        self.payment = QPlainTextEdit(self.profile.payment)
        self.payment.setPlaceholderText("How clients pay you, e.g. e-Transfer to you@example.com")
        self.payment.setFixedHeight(64)
        f.addRow("Payment instructions", self.payment)
        lay.addLayout(f)
        lay.addWidget(section("Taxes"))
        lay.addWidget(hint("None to start. Add the taxes you charge (e.g. GST 5); each client turns on the ones "
                           "that apply."))
        self.taxes = TaxTable(self.profile.taxes)
        lay.addWidget(self.taxes)
        self._number_preview()

        # 4. look and paper
        page, lay = self._page("Look and paper", "")
        lay.addWidget(section("Theme"))
        self.theme_group = QButtonGroup(self)
        for key, label in (("system", "Match Windows"), ("light", "Light"), ("dark", "Dark")):
            rb = QRadioButton(label)
            rb.setProperty("key", key)
            rb.setChecked(s.theme == key)
            self.theme_group.addButton(rb)
            lay.addWidget(rb)
        lay.addWidget(section("Paper"))
        self.page_size = combo([("letter", "Letter"), ("a4", "A4")],
                               self.profile.page_size if not first_run else locale_page_size())
        lay.addWidget(self.page_size)
        lay.addStretch(1)

        # 5. data and privacy
        page, lay = self._page("Your data stays on this PC", "")
        for line in ("Everything Docket Ledger saves stays on this computer:",
                     "No account, and nothing is uploaded.",
                     "Client details are never sent anywhere, including to AI apps."):
            lab = QLabel(("• " if not line.endswith(":") else "") + line)
            lab.setWordWrap(True)
            lay.addWidget(lab)
        folder = QLineEdit(str(data.folder))
        folder.setReadOnly(True)
        lay.addWidget(folder)
        lay.addWidget(section("Backups"))
        lay.addWidget(hint("Invoices are business records, and tax rules often require keeping them for several "
                           "years. Pick a folder such as OneDrive or a USB drive, and Ledger keeps a daily zip of "
                           "its data there. Off until you pick one."))
        row = QHBoxLayout()
        self.backup = QLineEdit(s.backup_dir)
        self.backup.setReadOnly(True)
        self.backup.setPlaceholderText("No backup folder")
        pick = QPushButton("Choose…")
        pick.clicked.connect(self._choose_backup)
        row.addWidget(self.backup, 1)
        row.addWidget(pick)
        lay.addLayout(row)
        lay.addWidget(section("Updates"))
        self.updates = QCheckBox("Check for updates when Docket Ledger starts")
        self.updates.setChecked(s.check_updates)
        lay.addWidget(self.updates)
        lay.addWidget(hint("This is the only time Docket Ledger goes online."))
        lay.addStretch(1)

        # 6. ready
        page, lay = self._page("You're ready", "Pick where to start. Everything here can be changed later in "
                                               "Settings and in your business profile.")
        self.ready_buttons: dict[str, QPushButton] = {}
        for key, label in (("invoice", "Make an invoice"), ("log", "Open a time log"),
                           ("sample", "Try a sample invoice")):
            b = QPushButton(label)
            b.setMinimumHeight(44)
            b.clicked.connect(lambda _=False, k=key: self._finish(k))
            lay.addWidget(b)
            self.ready_buttons[key] = b
        lay.addWidget(hint("The sample is made up and clearly marked; nothing from it is saved."))
        lay.addStretch(1)

        # navigation
        nav = QHBoxLayout()
        self.back_btn = QPushButton("Back")
        self.back_btn.clicked.connect(lambda: self._go(-1))
        self.next_btn = QPushButton("Next")
        self.next_btn.setProperty("primary", True)
        self.next_btn.clicked.connect(lambda: self._go(1))
        self.done_btn = QPushButton("Done")
        self.done_btn.clicked.connect(lambda: self._finish(""))
        nav.addWidget(self.back_btn)
        nav.addStretch(1)
        nav.addWidget(self.done_btn)
        nav.addWidget(self.next_btn)
        v.addLayout(nav)
        self._uses_changed()
        self._update_nav()

    # ---- pages
    def _page(self, title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel(title, objectName="SetupTitle"))
        if subtitle:
            lay.addWidget(hint(subtitle))
        lay.addSpacing(6)
        self.stack.addWidget(w)
        return w, lay

    def _visible(self) -> list[int]:
        out = [0, 1]
        if self.u_inv.isChecked() or self.u_sa.isChecked():
            out.append(2)
        return out + [3, 4, 5]

    def _go(self, step: int) -> None:
        pages = self._visible()
        i = pages.index(self.stack.currentIndex()) if self.stack.currentIndex() in pages else 0
        i = max(0, min(len(pages) - 1, i + step))
        self.stack.setCurrentIndex(pages[i])
        self._update_nav()

    def _update_nav(self) -> None:
        pages = self._visible()
        cur = self.stack.currentIndex()
        self.back_btn.setEnabled(cur != pages[0])
        last = cur == pages[-1]
        self.next_btn.setVisible(not last)
        self.done_btn.setVisible(cur != pages[0])

    def _uses_changed(self, *_) -> None:
        invoices = self.u_inv.isChecked() or self.u_sa.isChecked()
        docket = self.u_ts.isChecked() or self.u_inv.isChecked()
        if hasattr(self, "ready_buttons"):
            self.ready_buttons["invoice"].setVisible(invoices)
            self.ready_buttons["sample"].setVisible(invoices)
            self.ready_buttons["log"].setVisible(docket)
        if hasattr(self, "next_btn"):
            self.next_btn.setEnabled(invoices or docket)

    def _fmt(self) -> str:
        data = self.fmt.currentData()
        if data and self.fmt.currentText() == self.fmt.itemText(self.fmt.currentIndex()):
            return data
        return self.fmt.currentText().strip()

    def _number_preview(self, *_) -> None:
        fmt = self._fmt()
        if not number_format_ok(fmt):
            self.number_label.setText("Add a counter, e.g. {NN}")
            return
        n = self.next_n.value() if self.continuing.isChecked() else 1
        self.number_label.setText(f"First invoice: {format_number(fmt, dt.date.today(), n)}")

    def _choose_backup(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Backup folder", self.backup.text() or str(Path.home()))
        if path:
            self.backup.setText(path)

    # ---- finish
    def _finish(self, action: str) -> None:
        s = self.data.settings
        s.use_docket_timesheets = self.u_ts.isChecked()
        s.use_docket_invoices = self.u_inv.isChecked()
        s.use_standalone = self.u_sa.isChecked() or not (s.use_docket_timesheets or s.use_docket_invoices)
        s.currency = self.currency.currentData()
        s.terms_days = self.terms.value()
        fmt = self._fmt()
        s.number_format = fmt if number_format_ok(fmt) else DEFAULT_NUMBER_FORMAT
        if self.continuing.isChecked():
            s.set_next(dt.date.today(), self.next_n.value())
        checked = self.theme_group.checkedButton()
        s.theme = checked.property("key") if checked else "system"
        s.backup_dir = self.backup.text()
        s.check_updates = self.updates.isChecked()
        s.setup_done = True
        s.mode = "invoice" if (s.use_docket_invoices or s.use_standalone) and action != "log" else "timesheet"
        p = self.profile
        p.contact = self.contact.toPlainText()
        p.logo = self.logo.name
        p.accent = self.accent.value()
        p.layout = self.designer.current_layout()
        p.tax_number = self.tax_number.text().strip()
        p.payment = self.payment.toPlainText()
        p.taxes = self.taxes.taxes()
        p.page_size = self.page_size.currentData()
        self.data.replace_profile(p.name, p)
        s.last_profile = p.name
        self.data.save_settings()
        self.next_action = action
        self.accept()

    def reject(self) -> None:
        # closing setup still marks it done (with whatever is filled in), so it doesn't come back every launch
        self._finish("")


__all__ = ["SetupWizard", "locale_currency", "locale_page_size"]
