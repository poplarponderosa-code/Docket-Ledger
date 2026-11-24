"""Starts Docket Ledger: one window at a time; `--folder` and `--open` come from Docket."""
from __future__ import annotations

import argparse
import json
import sys

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from .store import Data
from .ui import theme
from .ui.main_window import MainWindow
from .ui.widgets import app_icon

SERVER_NAME = "DocketLedger-single-instance"
_RUNNING_MUTEX = None


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="DocketLedger", add_help=False)
    p.add_argument("--folder", default="")
    p.add_argument("--open", default="")
    p.add_argument("--updated", action="store_true")
    p.add_argument("path", nargs="?", default="")
    args, _ = p.parse_known_args(argv[1:])
    if not args.open and args.path:
        args.open = args.path
    return args


def send_to_running(args: argparse.Namespace) -> bool:
    """If Docket Ledger is already open, hand it the arguments and return True."""
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if not sock.waitForConnected(400):
        return False
    payload = json.dumps({"folder": args.folder, "open": args.open})
    sock.write(QByteArray(payload.encode("utf-8")))
    sock.flush()
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


def main(argv: list[str] | None = None) -> int:
    global _RUNNING_MUTEX
    argv = sys.argv if argv is None else argv
    args = parse_args(argv)
    if sys.platform == "win32":
        try:    # lets the installer ask to close Docket Ledger before updating it
            import ctypes
            _RUNNING_MUTEX = ctypes.windll.kernel32.CreateMutexW(None, False, "DocketLedgerRunningMutex")
        except Exception:      # noqa: BLE001
            pass
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(argv)
    app.setApplicationName("Docket Ledger")
    app.setOrganizationName("Docket")
    if send_to_running(args):
        return 0
    QLocalServer.removeServer(SERVER_NAME)
    server = QLocalServer()
    server.listen(SERVER_NAME)

    font = QFont()
    font.setFamilies(["Segoe UI Variable Text", "Segoe UI", "Inter", "Helvetica Neue", "Arial"])
    font.setPointSize(10)
    app.setFont(font)
    app.setWindowIcon(app_icon())

    data = Data()
    theme.set_current(theme.resolve(data.settings.theme))
    app.setStyleSheet(theme.stylesheet(theme.current, data.folder / "ui"))

    action = ""
    if not data.settings.setup_done:
        from .ui.setup import SetupWizard
        wizard = SetupWizard(data, None, first_run=True)
        wizard.exec()
        action = wizard.next_action
        theme.set_current(theme.resolve(data.settings.theme))
        app.setStyleSheet(theme.stylesheet(theme.current, data.folder / "ui"))

    win = MainWindow(data, cli_folder=args.folder)
    win.apply_theme()

    def on_connection() -> None:
        conn = server.nextPendingConnection()
        if conn is None:
            return

        def read() -> None:
            raw = bytes(conn.readAll()).decode("utf-8", errors="replace")
            try:
                msg = json.loads(raw) if raw.strip() else {}
            except ValueError:
                msg = {}
            win.handle_args(msg.get("folder", ""), msg.get("open", ""))

        if conn.bytesAvailable() or conn.waitForReadyRead(500):
            read()
        else:
            conn.readyRead.connect(read)

    server.newConnection.connect(on_connection)
    win.show()
    if args.open:
        win.open_log_path(args.open)
    elif action:
        win.do_action(action)
    return app.exec()
