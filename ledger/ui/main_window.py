"""The main window: logs and invoices on the left, the document in the middle, the preview on the right."""
from __future__ import annotations

import copy
import datetime as dt
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QFileSystemWatcher, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
                               QMainWindow, QMessageBox, QProgressDialog, QPushButton, QScrollArea, QSplitter,
                               QStackedWidget, QTabWidget, QToolButton, QVBoxLayout, QWidget, QMenu)

from .. import __version__, docket_link, updates
from ..logs import TimeLog, log_for_path, scan
from ..model import LogEdits
from ..store import Client, Data, Invoice, Profile
from . import theme
from .dialogs import ClientMatchDialog, ProfileDialog, SettingsDialog
from .history import HistoryPanel
from .invoice_panel import InvoicePanel
from .logs_panel import LogsPanel
from .preview import ZOOMS, PreviewView
from .timesheet_panel import TimesheetPanel, safe_filename
from .widgets import Segmented, app_icon, combo, section

MODES = [("timesheet", "Timesheet"), ("invoice", "Invoice")]


class MainWindow(QMainWindow):
    def __init__(self, data: Data, cli_folder: str = ""):
        super().__init__()
        self.data = data
        self.cli_folder = cli_folder
        self.setWindowTitle("Docket Ledger")
        self.resize(1440, 880)
        self.setMinimumSize(1000, 620)
        self._built = False
        self.logs: dict[str, TimeLog] = {}
        self.edits: dict[str, LogEdits] = {}
        self.opts = data.settings.table_options()
        self.preview_profile: Profile | None = None
        self.mode = data.settings.mode

        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(lambda _: self.rescan_timer.start())
        self.rescan_timer = QTimer(self, singleShot=True, interval=700, timeout=self.rescan)
        self.preview_timer = QTimer(self, singleShot=True, interval=300, timeout=self.update_preview)
        self.updater = updates.UpdateChecker(self)

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_top_bar())
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.addWidget(self._build_left())
        split.addWidget(self._build_center())
        split.addWidget(self._build_right())
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 2)
        split.setSizes([290, 500, 650])
        self.splitter = split
        outer.addWidget(split, 1)
        self.setCentralWidget(central)

        s = data.settings
        if s.window_geometry:
            self.restoreGeometry(QByteArray.fromBase64(s.window_geometry.encode("ascii")))
        if s.splitter_state:
            self.splitter.restoreState(QByteArray.fromBase64(s.splitter_state.encode("ascii")))

        self._built = True
        self.reload_profiles()
        self.apply_uses()
        self.rescan()
        self.set_mode(self.mode)
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(lambda *_: self.apply_theme() if self.data.settings.theme == "system"
                                             else None)
        if s.check_updates:
            QTimer.singleShot(4000, lambda: self.check_for_updates(manual=False))

    # ================================================================== layout
    def _build_top_bar(self) -> QWidget:
        bar = QWidget(objectName="TopBar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(12, 8, 12, 8)
        self.mode_toggle = Segmented(MODES, self.mode)
        self.mode_toggle.changed.connect(self.set_mode)
        h.addWidget(self.mode_toggle)
        self.new_invoice_btn = QPushButton("+ New invoice")
        self.new_invoice_btn.clicked.connect(self.new_invoice)
        h.addWidget(self.new_invoice_btn)
        h.addStretch(1)
        self.theme_btn = QToolButton(toolTip="Switch between light and dark")
        self.theme_btn.setProperty("flat", True)
        self.theme_btn.clicked.connect(self.toggle_theme)
        h.addWidget(self.theme_btn)
        settings = QToolButton(text="⚙", toolTip="Settings")
        settings.setProperty("flat", True)
        settings.clicked.connect(self.open_settings)
        h.addWidget(settings)
        return bar

    def _build_left(self) -> QWidget:
        w = QWidget(objectName="Panel")
        w.setMinimumWidth(240)
        v = QVBoxLayout(w)
        v.setContentsMargins(10, 10, 4, 10)
        self.left_tabs = QTabWidget()
        self.logs_panel = LogsPanel()
        self.logs_panel.selection_changed.connect(self._logs_changed)
        self.history = HistoryPanel(self.data)
        self.history.open_invoice.connect(self.open_invoice)
        self.history.invoice_again.connect(self.invoice_again)
        self.history.changed.connect(self._history_edited)
        self.left_tabs.addTab(self.logs_panel, "Time logs")
        self.left_tabs.addTab(self.history, "Invoices")
        v.addWidget(self.left_tabs, 1)
        return w

    def _build_center(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(430)
        body = QWidget(objectName="Panel")
        v = QVBoxLayout(body)
        v.setContentsMargins(10, 10, 10, 12)
        v.setSpacing(6)
        scroll.setWidget(body)
        v.addWidget(section("Your business"))
        row = QHBoxLayout()
        self.profile_combo = QComboBox()
        self.profile_combo.currentIndexChanged.connect(self._profile_changed)
        edit = QPushButton("Edit…")
        edit.clicked.connect(self.edit_profile)
        more = QToolButton(text="⋯", toolTip="More profile options")
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(more)
        for text, fn in (("New profile", self.new_profile), ("Duplicate", self.duplicate_profile),
                         ("Delete", self.delete_profile), (None, None), ("Import…", self.import_profile),
                         ("Export…", self.export_profile)):
            if text is None:
                menu.addSeparator()
            else:
                menu.addAction(QAction(text, menu, triggered=fn))
        more.setMenu(menu)
        row.addWidget(self.profile_combo, 1)
        row.addWidget(edit)
        row.addWidget(more)
        v.addLayout(row)
        self.stack = QStackedWidget()
        self.ts_panel = TimesheetPanel(self)
        self.ts_panel.changed.connect(self.schedule_preview)
        self.inv_panel = InvoicePanel(self)
        self.inv_panel.changed.connect(self.schedule_preview)
        self.inv_panel.exported.connect(self.history_changed)
        self.stack.addWidget(self.ts_panel)
        self.stack.addWidget(self.inv_panel)
        v.addWidget(self.stack, 1)
        return scroll

    def _build_right(self) -> QWidget:
        w = QWidget(objectName="Panel")
        v = QVBoxLayout(w)
        v.setContentsMargins(6, 10, 12, 12)
        top = QHBoxLayout()
        top.addWidget(section("Preview"))
        top.addStretch(1)
        self.pages_label = QLabel(objectName="Muted")
        top.addWidget(self.pages_label)
        self.zoom = combo(ZOOMS, self.data.settings.zoom)
        self.zoom.currentIndexChanged.connect(self._zoom_changed)
        top.addWidget(self.zoom)
        v.addLayout(top)
        self.preview = PreviewView()
        self.preview.zoom = self.data.settings.zoom
        v.addWidget(self.preview, 1)
        bottom = QHBoxLayout()
        self.open_pdf = QCheckBox("Open PDF")
        self.open_pdf.setChecked(self.data.settings.open_pdf)
        self.open_folder = QCheckBox("Open folder")
        self.open_folder.setChecked(self.data.settings.open_folder)
        for cb in (self.open_pdf, self.open_folder):
            cb.toggled.connect(self._export_prefs)
        bottom.addWidget(QLabel("After export:", objectName="Muted"))
        bottom.addWidget(self.open_pdf)
        bottom.addWidget(self.open_folder)
        bottom.addStretch(1)
        self.email_btn = QPushButton("Copy email text")
        self.email_btn.setToolTip("A ready-made message with the invoice number, amount and due date")
        self.email_btn.clicked.connect(lambda: self.inv_panel.copy_email())
        bottom.addWidget(self.email_btn)
        self.export_btn = QPushButton("Export PDF…")
        self.export_btn.setProperty("primary", True)
        self.export_btn.clicked.connect(self.export)
        bottom.addWidget(self.export_btn)
        v.addLayout(bottom)
        return w

    # ================================================================== uses, modes, theme
    def apply_uses(self) -> None:
        s = self.data.settings
        can_ts, can_inv = s.uses_timesheets, s.uses_invoices
        self.mode_toggle.setVisible(can_ts and can_inv)
        self.left_tabs.setTabVisible(0, s.uses_docket)
        self.left_tabs.setTabVisible(1, can_inv)
        if not can_ts and self.mode == "timesheet":
            self.set_mode("invoice")
        elif not can_inv and self.mode == "invoice":
            self.set_mode("timesheet")

    def set_mode(self, mode: str) -> None:
        s = self.data.settings
        if mode == "timesheet" and not s.uses_timesheets and s.uses_invoices:
            mode = "invoice"
        if mode == "invoice" and not s.uses_invoices:
            mode = "timesheet"
        self.mode = mode
        s.mode = mode
        self.mode_toggle.set_value(mode)
        self.stack.setCurrentWidget(self.inv_panel if mode == "invoice" else self.ts_panel)
        self.new_invoice_btn.setVisible(mode == "invoice")
        self.email_btn.setVisible(mode == "invoice")
        if mode == "invoice":
            inv = self.inv_panel.inv
            keys = {r.get("key") for r in inv.log_refs}
            if not keys and inv.status == "draft" and not inv.sample and not inv.lines and self.ts_panel.keys \
                    and self.data.settings.use_docket_invoices:
                keys = set(self.ts_panel.keys)      # the timesheet's logs become the new invoice's logs
            self._lock_logs()
            self.logs_panel.set_ticked(keys)
        else:
            self.logs_panel.set_mode("timesheet")
            self.logs_panel.set_enabled_ticks(True)
            keys = {r.get("key") for r in self.inv_panel.inv.log_refs if r.get("key") in self.logs}
            if keys:
                self.logs_panel.set_ticked(keys, current=next(iter(keys)))
            else:
                self._logs_changed()
        self.save_settings()
        self.schedule_preview()

    def _lock_logs(self) -> None:
        inv = self.inv_panel.inv
        locked = self.mode == "invoice" and (inv.status != "draft" or inv.sample)
        self.logs_panel.set_mode("locked" if locked else self.mode)
        self.logs_panel.set_enabled_ticks(not locked)

    def apply_theme(self) -> None:
        name = theme.resolve(self.data.settings.theme)
        theme.set_current(name)
        app = QApplication.instance()
        app.setStyleSheet(theme.stylesheet(theme.current, self.data.folder / "ui"))
        icon = app_icon(theme.PALETTES["light"]["accent"])
        app.setWindowIcon(icon)
        self.setWindowIcon(icon)
        self.theme_btn.setText("☀" if name == "dark" else "☾")
        if self._built:
            self.ts_panel.table.refresh()
            self.history.refresh()
            self.schedule_preview()

    def toggle_theme(self) -> None:
        current = theme.resolve(self.data.settings.theme)
        self.data.settings.theme = "light" if current == "dark" else "dark"
        self.save_settings()
        self.apply_theme()

    # ================================================================== logs
    def logs_dir(self) -> Path | None:
        s = self.data.settings
        if s.logs_dir and Path(s.logs_dir).is_dir():
            return Path(s.logs_dir)
        if self.cli_folder and Path(self.cli_folder).is_dir():
            return Path(self.cli_folder)
        return docket_link.logs_dir()

    def rescan(self) -> None:
        folder = self.logs_dir()
        old = self.watcher.directories()
        if old:
            self.watcher.removePaths(old)
        if folder is not None:
            self.watcher.addPath(str(folder))
            self.logs_panel.folder_label.setText(f"Folder: {folder}")
        else:
            self.logs_panel.folder_label.setText("Docket's time logs folder wasn't found. Choose it in "
                                                 "Settings (⚙).")
        found = scan(folder)
        new = {lg.key: lg for lg in found}
        for key, lg in self.logs.items():          # logs opened from elsewhere stay listed
            if key not in new and (folder is None or lg.folder != folder) and lg.path and lg.path.exists():
                refreshed = log_for_path(lg.path)
                if refreshed:
                    new[key] = refreshed
        for key, lg in new.items():
            prev = self.logs.get(key)
            if key in self.edits and prev is not None and prev.mtime != lg.mtime and not self.edits[key].changed:
                self.edits[key] = LogEdits.from_log(lg)
        self.logs = new
        self.edits = {k: e for k, e in self.edits.items() if k in new}
        self.fill_logs()

    def fill_logs(self, select: str | None = None, ticked: set[str] | None = None) -> None:
        ordered = sorted(self.logs.values(), key=lambda lg: lg.sort_time, reverse=True)
        self.logs_panel.fill(ordered, self.data.invoices.invoiced_logs(), select, ticked)
        self._lock_logs()
        self._logs_changed()

    def ensure_edits(self, key: str) -> LogEdits:
        if key not in self.edits:
            self.edits[key] = LogEdits.from_log(self.logs[key])
        return self.edits[key]

    def tick_logs(self, keys: list[str]) -> None:
        self._lock_logs()
        self.logs_panel.set_ticked(set(keys), current=keys[0] if keys else None)

    def _logs_changed(self) -> None:
        if not self._built:
            return
        checked = self.logs_panel.checked()
        if self.mode == "invoice":
            self.inv_panel.set_logs(checked)
        else:
            cur = self.logs_panel.current()
            keys = checked or ([cur] if cur else [])
            self.ts_panel.set_logs([k for k in keys if k in self.logs])
        self.schedule_preview()

    def open_log_path(self, path: str) -> None:
        """--open from Docket: show that log (timesheet), or start an invoice from it."""
        lg = log_for_path(Path(path))
        if lg is None:
            QMessageBox.warning(self, "Docket Ledger", f"Couldn't open this time log:\n{path}")
            return
        self.logs.setdefault(lg.key, lg)
        self.fill_logs(select=lg.key, ticked=set())
        if self.mode == "invoice":
            inv = self.inv_panel.inv
            if inv.status != "draft" or inv.sample or inv.lines or inv.log_refs:
                self.inv_panel.new_invoice()
            self.tick_logs([lg.key])
        else:
            self.tick_logs([])
            self.logs_panel.set_ticked(set(), current=lg.key)
        self.left_tabs.setCurrentWidget(self.logs_panel)
        self.bring_to_front()

    def handle_args(self, folder: str, open_path: str) -> None:
        if folder and folder != self.cli_folder:
            self.cli_folder = folder
            self.rescan()
        if open_path:
            self.open_log_path(open_path)
        else:
            self.bring_to_front()

    def bring_to_front(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def known_categories(self) -> list[str]:
        seen: dict[str, str] = {}
        for lg in self.logs.values():
            for c in lg.categories():
                if c:
                    seen.setdefault(c.lower(), c)
        for c in self.data.category_names():
            seen.setdefault(c.lower(), c)
        return sorted(seen.values(), key=str.lower)

    # ================================================================== clients
    def match_client(self, label: str, ask: bool = True) -> Client | None:
        found = self.data.client_for_label(label)
        if found is not None or not ask:
            return found
        d = ClientMatchDialog(self.data, label, self)
        d.exec()
        if d.choice == "use":
            c = self.data.client(d.pick.currentData())
            if c is not None and d.remember.isChecked():
                if not c.label:
                    c.label = label
                elif label.lower() not in [a.lower() for a in c.aliases]:
                    c.aliases.append(label)
                self.data.upsert_client(c)
            return c
        if d.choice == "new":
            return self.inv_panel.new_client(label=label)
        return None

    def clients_changed(self) -> None:
        if docket_link.docket_installed():
            docket_link.write_categories(self.data.category_names())
        self.ts_panel.reload_clients()
        self.inv_panel.reload_clients()
        self.schedule_preview()

    # ================================================================== invoices
    def new_invoice(self) -> None:
        self.set_mode("invoice")
        self.inv_panel.new_invoice()
        self.tick_logs([])

    def open_invoice(self, inv: Invoice) -> None:
        self.set_mode("invoice")
        self.inv_panel.open_invoice(inv)

    def invoice_again(self, inv: Invoice) -> None:
        self.set_mode("invoice")
        self.inv_panel.again(inv)

    def on_invoice_loaded(self, inv: Invoice) -> None:
        if self._built:
            self._lock_logs()

    def history_changed(self) -> None:
        if not self._built:
            return
        self.history.refresh()
        self.fill_logs(ticked=set(self.logs_panel.checked()))

    def _history_edited(self) -> None:
        # a status change in History: reload the open invoice if it's the same one
        cur = self.inv_panel.inv
        fresh = self.data.invoices.invoices.get(cur.id)
        if fresh is not None and fresh is not cur and not cur.sample:
            cur.status, cur.paid_date = fresh.status, fresh.paid_date
            self.inv_panel._update_status()
        elif fresh is None and cur.created and not cur.sample:          # its draft was deleted
            self.inv_panel.new_invoice()
        self.fill_logs(ticked=set(self.logs_panel.checked()))
        self.schedule_preview()

    # ================================================================== profiles
    def profile(self) -> Profile:
        return self.preview_profile or self.data.profile(self.profile_combo.currentText()
                                                         if hasattr(self, "profile_combo") else "")

    def author(self, profile: Profile) -> str:
        return profile.contact.strip().split("\n")[0] if profile.contact.strip() else ""

    def reload_profiles(self, select: str | None = None) -> None:
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for p in self.data.profiles:
            self.profile_combo.addItem(p.name)
        i = self.profile_combo.findText(select or self.data.settings.last_profile)
        self.profile_combo.setCurrentIndex(max(0, i))
        self.profile_combo.blockSignals(False)
        self._profile_changed()

    def _profile_changed(self, *_) -> None:
        self.data.settings.last_profile = self.profile_combo.currentText()
        self.save_settings()
        if self._built:
            self.inv_panel.profile_changed()
        self.schedule_preview()

    def edit_profile(self) -> None:
        name = self.profile_combo.currentText()

        def live(p: Profile) -> None:
            self.preview_profile = p
            self.schedule_preview()

        d = ProfileDialog(self.data, name, live, self)
        ok = d.exec()
        self.preview_profile = None
        if ok:
            p = d.current()
            self.data.replace_profile(name, p)
            self.reload_profiles(p.name)
        else:
            self.schedule_preview()

    def new_profile(self) -> None:
        name, ok = QInputDialog.getText(self, "New profile", "Profile name:")
        if ok and name.strip():
            p = Profile(name=self.data.unique_profile_name(name.strip()))
            self.data.profiles.append(p)
            self.data.save_profiles()
            self.reload_profiles(p.name)
            self.edit_profile()

    def duplicate_profile(self) -> None:
        p = Profile.from_dict(copy.deepcopy(self.data.profile(self.profile_combo.currentText()).to_dict()))
        p.name = self.data.unique_profile_name(f"{p.name} copy")
        for attr in ("logo", "watermark"):
            path = self.data.image_path(getattr(p, attr))
            setattr(p, attr, self.data.import_image(path) if path else "")
        self.data.profiles.append(p)
        self.data.save_profiles()
        self.reload_profiles(p.name)

    def delete_profile(self) -> None:
        name = self.profile_combo.currentText()
        if len(self.data.profiles) <= 1:
            QMessageBox.information(self, "Docket Ledger", "There must be at least one profile.")
            return
        if QMessageBox.question(self, "Delete profile", f"Delete the profile “{name}”?") \
                == QMessageBox.StandardButton.Yes:
            self.data.delete_profile(name)
            self.reload_profiles()

    def import_profile(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import profile", str(Path.home() / "Documents"),
                                              "Docket Ledger profile (*.json)")
        if not path:
            return
        try:
            p = self.data.import_profile(Path(path))
        except Exception as e:      # noqa: BLE001
            QMessageBox.warning(self, "Import profile", f"Couldn't import this profile.\n{e}")
            return
        self.reload_profiles(p.name)

    def export_profile(self) -> None:
        name = self.profile_combo.currentText()
        path, _ = QFileDialog.getSaveFileName(self, "Export profile",
                                              str(Path.home() / "Documents" / f"{safe_filename(name)}.json"),
                                              "Docket Ledger profile (*.json)")
        if path:
            try:
                self.data.export_profile(name, Path(path))
            except OSError as e:
                QMessageBox.warning(self, "Export profile", f"Couldn't save the profile.\n{e}")

    # ================================================================== preview and export
    def active_panel(self):
        return self.inv_panel if self.mode == "invoice" else self.ts_panel

    def schedule_preview(self) -> None:
        if self._built:
            self.preview_timer.start()

    def build_now(self):
        try:
            return self.active_panel().build(self.profile())
        except Exception as e:      # noqa: BLE001 - shown in the preview rather than crashing
            self.preview.show_message(f"The PDF couldn't be built.\n{e}")
            return None

    def update_preview(self) -> None:
        panel = self.active_panel()
        if not panel.has_document():
            self.preview.show_message(panel.empty_message())
            self.pages_label.setText("")
            self.export_btn.setEnabled(False)
            return
        self.export_btn.setEnabled(True)
        result = self.build_now()
        if result is None:
            return
        self.preview.set_pdf(result.data)
        self.pages_label.setText(f"{result.pages} page{'s' if result.pages != 1 else ''}")

    def _zoom_changed(self) -> None:
        self.data.settings.zoom = self.zoom.currentData()
        self.preview.set_zoom(self.data.settings.zoom)
        self.save_settings()

    def _export_prefs(self) -> None:
        self.data.settings.open_pdf = self.open_pdf.isChecked()
        self.data.settings.open_folder = self.open_folder.isChecked()
        self.save_settings()

    def export(self) -> None:
        self.active_panel().export()

    def ask_pdf_path(self, name: str) -> Path | None:
        s = self.data.settings
        folder = s.last_export_dir if Path(s.last_export_dir or "").is_dir() else str(Path.home() / "Documents")
        path, _ = QFileDialog.getSaveFileName(self, "Export PDF", str(Path(folder) / name), "PDF (*.pdf)")
        if not path:
            return None
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        return Path(path)

    def save_pdf(self, data: bytes, name: str) -> Path | None:
        path = self.ask_pdf_path(name)
        if path is None:
            return None
        try:
            path.write_bytes(data)
        except OSError as e:
            QMessageBox.warning(self, "Export PDF", f"Couldn't save the PDF. Is it open in another app?\n{e}")
            return None
        self.after_export(path)
        return path

    def after_export(self, path: Path) -> None:
        s = self.data.settings
        s.last_export_dir = str(path.parent)
        self.save_settings()
        if self.open_pdf.isChecked():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        if self.open_folder.isChecked():
            if sys.platform == "win32":
                subprocess.Popen(f'explorer /select,"{path}"')
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
        self.daily_backup()
        self.status(f"Saved {path.name}")
        self.history_changed()

    def status(self, text: str) -> None:
        self.statusBar().showMessage(text, 6000)

    # ================================================================== settings, backups, updates
    def open_settings(self) -> None:
        d = SettingsDialog(self.data, docket_link.logs_dir(), __version__, self,
                           on_check_updates=lambda: self.check_for_updates(manual=True))
        if not d.exec():
            return
        old_dir = self.data.settings.logs_dir
        self.data.settings = d.result_settings()
        self.save_settings()
        self.opts = self.data.settings.table_options()
        self.ts_panel.apply_options()
        self.apply_theme()
        self.apply_uses()
        if self.data.settings.logs_dir != old_dir:
            self.rescan()
        self.schedule_preview()
        if d.run_setup:
            self.run_setup()

    def run_setup(self) -> None:
        from .setup import SetupWizard
        w = SetupWizard(self.data, self, first_run=False)
        w.exec()
        self.reload_profiles()
        self.apply_theme()
        self.apply_uses()
        self.do_action(w.next_action)

    def do_action(self, action: str) -> None:
        if action == "invoice":
            self.new_invoice()
        elif action == "sample":
            self.set_mode("invoice")
            self.inv_panel.load_sample()
        elif action == "log":
            self.set_mode("timesheet")
            self.left_tabs.setCurrentWidget(self.logs_panel)

    def save_settings(self) -> None:
        try:
            self.data.save_settings()
        except OSError:
            pass

    def daily_backup(self) -> None:
        s = self.data.settings
        if s.backup_dir and s.last_backup != dt.date.today().isoformat():
            try:
                self.data.backup()
            except OSError as e:
                self.status(f"Backup failed: {e}")

    def check_for_updates(self, manual: bool = True) -> None:
        def result(release, error) -> None:
            if release is None:
                if manual:
                    QMessageBox.information(self, "Updates", f"Couldn't check for updates right now.\n\n{error}")
                return
            tag = release.get("tag_name", "")
            if not updates.is_newer(tag):
                if manual:
                    QMessageBox.information(self, "Updates", f"You have the latest version ({__version__}).")
                return
            if not manual and tag == self.data.settings.skipped_version:
                return
            self._offer_update(release)

        self.updater.check(result)

    def _offer_update(self, release: dict) -> None:
        tag = release.get("tag_name", "")
        notes = (release.get("body") or "").strip()
        box = QMessageBox(self)
        box.setWindowTitle("Update available")
        box.setText(f"Docket Ledger {tag.lstrip('vV')} is available. You have {__version__}.")
        if notes:
            box.setInformativeText(notes[:600] + ("…" if len(notes) > 600 else ""))
        now_btn = box.addButton("Update now", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        skip_btn = box.addButton("Skip this version", QMessageBox.ButtonRole.DestructiveRole)
        box.exec()
        if box.clickedButton() == skip_btn:
            self.data.settings.skipped_version = tag
            self.save_settings()
        elif box.clickedButton() == now_btn:
            self._download_update(release)

    def _download_update(self, release: dict) -> None:
        asset = updates.pick_installer(release)
        page = release.get("html_url") or updates.RELEASES_PAGE
        if not getattr(sys, "frozen", False) or asset is None:
            QDesktopServices.openUrl(QUrl(page))
            return
        name, url = asset
        dest = updates.download_path(name)
        progress = QProgressDialog("Downloading the update…", "Cancel", 0, 100, self)
        progress.setWindowTitle("Updating Docket Ledger")
        progress.setMinimumDuration(0)
        progress.canceled.connect(self.updater.cancel)

        def on_progress(received: int, total: int) -> None:
            if total > 0:
                progress.setValue(int(received * 100 / total))

        def on_done(path, error) -> None:
            progress.close()
            if path is None:
                if error and "cancel" not in error.lower():
                    QMessageBox.warning(self, "Update", f"The download didn't finish: {error}")
                return
            self.inv_panel.save_now()
            if updates.run_installer_and_quit_soon(path):
                QApplication.instance().quit()
            else:
                QDesktopServices.openUrl(QUrl(page))

        self.updater.download(url, dest, on_progress, on_done)

    def closeEvent(self, e) -> None:
        self.inv_panel.save_now()
        s = self.data.settings
        s.window_geometry = bytes(self.saveGeometry().toBase64()).decode("ascii")
        s.splitter_state = bytes(self.splitter.saveState().toBase64()).decode("ascii")
        self.save_settings()
        self.daily_backup()
        super().closeEvent(e)

