"""Check GitHub for a newer Docket Ledger release, download its installer, and run it."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from . import __version__

GITHUB_REPO = "poplarponderosa-code/Docket-Ledger"
API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases/latest"


def parse_version(tag: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", tag or "")
    return tuple(int(n) for n in nums[:3]) if nums else (0,)


def is_newer(tag: str, current: str = __version__) -> bool:
    return parse_version(tag) > parse_version(current)


def pick_installer(release: dict) -> tuple[str, str] | None:
    """(file name, download url) of the release's setup .exe."""
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if name.lower().endswith(".exe") and "setup" in name.lower():
            return name, asset.get("browser_download_url", "")
    return None


def parse_release(body: bytes) -> dict | None:
    try:
        data = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or "tag_name" not in data:
        return None
    return data


def installer_command(path: Path) -> str:
    """The full cmd.exe command line that waits ~2 seconds, then starts the installer quietly.

    Built as one string on purpose: handing subprocess a list makes Python escape the inner
    quotes as \\" which cmd.exe doesn't understand, so `start` ended up looking for a file
    called \\ (the 1.1.0 and 1.2.0 updater bug)."""
    return (f'cmd.exe /c ping -n 3 127.0.0.1 >nul & start "" "{path}" '
            f'/SILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS')


def run_installer_and_quit_soon(path: Path) -> bool:
    """Start the downloaded installer quietly a couple of seconds from now, so Docket Ledger can close
    first. The installer reopens Docket Ledger when it's done."""
    if sys.platform != "win32":
        return False
    try:
        subprocess.Popen(installer_command(path), creationflags=0x08000000)   # no console window
    except OSError:
        return False
    return True


def download_path(name: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", name) or "DocketLedger-Setup.exe"
    return Path(tempfile.gettempdir()) / safe


class UpdateChecker:
    """Thin wrapper over QNetworkAccessManager. Callbacks keep it simple to wire up."""

    def __init__(self, parent=None):
        from PySide6.QtNetwork import QNetworkAccessManager
        self.net = QNetworkAccessManager(parent)
        self._reply = None

    def _request(self, url: str):
        from PySide6.QtCore import QUrl
        from PySide6.QtNetwork import QNetworkRequest
        req = QNetworkRequest(QUrl(url))
        req.setRawHeader(b"User-Agent", f"DocketLedger/{__version__}".encode())
        req.setRawHeader(b"Accept", b"application/vnd.github+json")
        return req

    def check(self, on_result, url: str = API_LATEST) -> None:
        """on_result(release_dict_or_None, error_text_or_empty). A repo with no release gives None."""
        reply = self.net.get(self._request(url))

        def done() -> None:
            from PySide6.QtNetwork import QNetworkReply
            if reply.error() != QNetworkReply.NetworkError.NoError:
                on_result(None, reply.errorString())
            else:
                release = parse_release(bytes(reply.readAll()))
                on_result(release, "" if release else "GitHub sent something unexpected")
            reply.deleteLater()

        reply.finished.connect(done)

    def download(self, url: str, dest: Path, on_progress, on_done) -> None:
        """on_progress(received, total); on_done(path_or_None, error_text)."""
        reply = self.net.get(self._request(url))
        self._reply = reply
        try:
            fh = open(dest, "wb")
        except OSError as e:
            on_done(None, str(e))
            reply.abort()
            return

        def ready() -> None:
            fh.write(bytes(reply.readAll()))

        def done() -> None:
            from PySide6.QtNetwork import QNetworkReply
            fh.write(bytes(reply.readAll()))
            fh.close()
            if reply.error() != QNetworkReply.NetworkError.NoError:
                on_done(None, reply.errorString())
            else:
                on_done(dest, "")
            reply.deleteLater()
            self._reply = None

        reply.readyRead.connect(ready)
        reply.downloadProgress.connect(on_progress)
        reply.finished.connect(done)

    def cancel(self) -> None:
        if self._reply is not None:
            self._reply.abort()
