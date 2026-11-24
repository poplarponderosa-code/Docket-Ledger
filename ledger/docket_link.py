"""The only file Docket and Ledger share: %APPDATA%\\Docket\\shared.json.

Ledger reads the time logs folder from it, and writes one thing back: the combined list of
category names that have rates ("categories"). Never client names, labels or rates.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def docket_dir() -> Path:
    override = os.environ.get("DOCKET_DATA")
    if override:
        return Path(override)
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home())) / "Docket"
    return Path.home() / ".local" / "share" / "docket"


def shared_path() -> Path:
    return docket_dir() / "shared.json"


def docket_installed() -> bool:
    return shared_path().exists()


def read_shared() -> dict:
    try:
        data = json.loads(shared_path().read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def logs_dir(shared: dict | None = None) -> Path | None:
    shared = read_shared() if shared is None else shared
    value = shared.get("timelog_dir")
    if isinstance(value, str) and value and Path(value).is_dir():
        return Path(value)
    return None


def write_categories(names: list[str]) -> bool:
    """Adds or updates the "categories" key, keeping every other key. Only when Docket is installed."""
    path = shared_path()
    if not path.exists():
        return False
    data = read_shared()
    clean = sorted({n.strip() for n in names if n and n.strip()}, key=str.lower)
    if data.get("categories") == clean:
        return True
    data["categories"] = clean
    tmp = path.with_suffix(".ledger.tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        return False
    return True
