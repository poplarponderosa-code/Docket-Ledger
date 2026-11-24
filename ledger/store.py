"""Everything Docket Ledger saves, as JSON in its own folder. No Qt in here.

  settings.json   app settings (uses, theme, folders, table defaults, invoice numbering)
  profiles.json   business profiles: letterhead, layout, page setup, taxes, payment details
  clients.json    clients: label, bill-to, currency, terms, category rates, taxes
  items.json      saved items for invoices
  invoices/       one file per invoice (drafts included)
  images/         logos and watermarks, copied in so moving the originals breaks nothing

Client details live only here. Nothing in this folder is shared with Docket or any other app.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
import re
import shutil
import sys
import uuid
import zipfile
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .model import TableOptions, category_key, default_columns, normalise_columns

APP_NAME = "Docket Ledger"


def data_dir() -> Path:
    override = os.environ.get("DOCKET_LEDGER_DATA")
    if override:
        path = Path(override)
    elif sys.platform == "win32":
        path = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
    else:
        path = Path.home() / ".local" / "share" / "docket-ledger"
    path.mkdir(parents=True, exist_ok=True)
    return path


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def _write_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _from_dict(cls, d: dict):
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in (d or {}).items() if k in names})


MARGINS_MM = {"narrow": 12.7, "normal": 19.05, "wide": 25.4}
FONT_SIZES = {"small": 9.0, "normal": 10.5, "large": 12.0}
PAGE_NUMBER_POSITIONS = [("off", "Off"), ("footer-left", "Footer, left"), ("footer-center", "Footer, centre"),
                         ("footer-right", "Footer, right"), ("header-right", "Header, right")]
PAGE_NUMBER_STYLES = [("page-of", "Page 1 of 3"), ("slash", "1 / 3"), ("plain", "1")]

# ---- layout ----------------------------------------------------------------------------------------
SLOTS = ["top-left", "top-center", "top-right", "info-left", "info-right"]
ELEMENTS = {"logo": "Logo", "sender": "Your details", "billto": "Bill to", "details": "Invoice details"}
PRESETS = {
    "classic": ("Classic", {"logo": "top-left", "sender": "top-right", "billto": "info-left", "details": "info-right"}),
    "centred": ("Centred", {"logo": "top-center", "sender": "top-center", "billto": "info-left",
                            "details": "info-right"}),
    "compact": ("Compact", {"logo": "top-left", "sender": "top-left", "billto": "info-left",
                            "details": "top-right"}),
}


def normalise_layout(layout: dict | None) -> dict:
    base = dict(PRESETS["classic"][1])
    for k, v in (layout or {}).items():
        if k in ELEMENTS and v in SLOTS:
            base[k] = v
    return base


# ---- business profile ----------------------------------------------------------------------------
@dataclass
class Profile:
    name: str = "My business"
    contact: str = ""                    # your details block; first line shown in bold
    tax_number: str = ""                 # e.g. "GST/HST no. 12345 6789 RT0001"
    payment: str = ""                    # payment instructions printed on invoices
    logo: str = ""                       # file in the images folder ("" = none)
    logo_height_mm: float = 18.0
    accent: str = ""                     # table header colour; "" = taken from the logo
    header_text: str = "auto"            # auto | light | dark
    layout: dict = field(default_factory=lambda: dict(PRESETS["classic"][1]))
    preset: str = "classic"
    watermark: str = ""
    watermark_size: int = 60
    watermark_opacity: int = 10
    footer: str = ""
    page_size: str = "letter"            # letter | a4
    orientation: str = "portrait"
    margins: str = "normal"
    heading_font: str = ""
    body_font: str = ""
    font_size: str = "normal"
    page_numbers: str = "footer-right"
    page_number_style: str = "page-of"
    page_number_first: bool = True
    show_generated: bool = True
    show_date_range: bool = True
    taxes: list = field(default_factory=list)       # [{"id", "name", "rate"}]

    @classmethod
    def from_dict(cls, d: dict) -> "Profile":
        p = _from_dict(cls, d)
        p.page_size = p.page_size if p.page_size in ("letter", "a4") else "letter"
        p.orientation = p.orientation if p.orientation in ("portrait", "landscape") else "portrait"
        p.margins = p.margins if p.margins in MARGINS_MM else "normal"
        p.font_size = p.font_size if p.font_size in FONT_SIZES else "normal"
        if p.accent and not re.fullmatch(r"#[0-9A-Fa-f]{6}", p.accent):
            p.accent = ""
        p.header_text = p.header_text if p.header_text in ("auto", "light", "dark") else "auto"
        p.layout = normalise_layout(p.layout)
        p.taxes = [{"id": t.get("id") or new_id(), "name": str(t.get("name", "")), "rate": str(t.get("rate", ""))}
                   for t in (p.taxes or []) if isinstance(t, dict)]
        return p

    def to_dict(self) -> dict:
        return asdict(self)


# ---- clients -----------------------------------------------------------------------------------------
@dataclass
class Client:
    id: str = field(default_factory=new_id)
    label: str = ""                      # matches Docket's client: field (e.g. "Acme")
    aliases: list = field(default_factory=list)     # other labels remembered for this client
    name: str = ""                       # shown in bold on the invoice
    bill_to: str = ""                    # address and contact lines
    email: str = ""
    currency: str = "CAD"
    terms_days: int = 30
    default_rate: str = ""               # for categories without their own rate
    rates: dict = field(default_factory=dict)       # category label -> rate
    taxes: list = field(default_factory=list)       # ids of the profile's tax lines that apply
    notes: str = ""

    @property
    def display(self) -> str:
        return self.name or self.label or "Unnamed client"

    def matches(self, label: str) -> bool:
        k = (label or "").strip().lower()
        return bool(k) and k in {x.strip().lower() for x in [self.label, *self.aliases] if x}

    def rate_for(self, category: str) -> str:
        k = category_key(category)
        for name, rate in self.rates.items():
            if category_key(name) == k and str(rate).strip():
                return str(rate)
        return str(self.default_rate or "")


@dataclass
class SavedItem:
    id: str = field(default_factory=new_id)
    description: str = ""
    kind: str = "hours"                  # hours | fixed | qty
    unit: str = ""
    price: str = ""
    category: str = ""


# ---- invoices ------------------------------------------------------------------------------------------
@dataclass
class Invoice:
    id: str = field(default_factory=new_id)
    number: str = ""                     # given when first exported, never reused
    status: str = "draft"                # draft | sent | paid
    title: str = "Invoice"
    created: str = ""
    updated: str = ""
    issue_date: str = ""                 # YYYY-MM-DD
    terms_days: int = 30
    due_date: str = ""
    client_id: str = ""
    client_snapshot: dict = field(default_factory=dict)   # name, label, bill_to, email as printed
    currency: str = "CAD"
    profile: str = ""
    log_refs: list = field(default_factory=list)  # [{key, path, title, finished, seconds, categories}]
    rounding: str = "off"
    round_each_row: bool = False
    category_rates: dict = field(default_factory=dict)    # category key -> rate typed on this invoice
    lines: list = field(default_factory=list)             # [{kind, description, category, qty, unit, price}]
    discount_kind: str = "none"          # none | percent | amount
    discount_value: str = ""
    taxes: list = field(default_factory=list)             # [{id, name, rate, on}]
    notes: str = ""
    attach_timesheet: bool = True
    paid_date: str = ""
    subtotal: str = ""
    total: str = ""                      # snapshot when exported, for History
    pdf_path: str = ""
    sample: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> "Invoice":
        inv = _from_dict(cls, d)
        inv.status = inv.status if inv.status in ("draft", "sent", "paid") else "draft"
        return inv

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def issue(self) -> dt.date:
        try:
            return dt.date.fromisoformat(self.issue_date)
        except ValueError:
            return dt.date.today()

    @property
    def due(self) -> dt.date | None:
        try:
            return dt.date.fromisoformat(self.due_date)
        except ValueError:
            return None

    def overdue(self, today: dt.date | None = None) -> bool:
        today = today or dt.date.today()
        return self.status == "sent" and self.due is not None and self.due < today

    @property
    def client_name(self) -> str:
        return self.client_snapshot.get("name") or self.client_snapshot.get("label") or ""


class InvoiceStore:
    def __init__(self, folder: Path):
        self.folder = folder / "invoices"
        self.folder.mkdir(parents=True, exist_ok=True)
        self.invoices: dict[str, Invoice] = {}
        self.load()

    def load(self) -> None:
        self.invoices = {}
        for f in self.folder.glob("*.json"):
            d = _read_json(f, None)
            if isinstance(d, dict):
                inv = Invoice.from_dict(d)
                self.invoices[inv.id] = inv

    def save(self, inv: Invoice) -> None:
        if inv.sample:
            return
        now = dt.datetime.now().isoformat(timespec="seconds")
        inv.created = inv.created or now
        inv.updated = now
        self.invoices[inv.id] = inv
        _write_json(self.folder / f"{inv.id}.json", inv.to_dict())

    def delete(self, inv: Invoice) -> None:
        self.invoices.pop(inv.id, None)
        try:
            (self.folder / f"{inv.id}.json").unlink()
        except OSError:
            pass

    def all(self) -> list[Invoice]:
        return sorted(self.invoices.values(), key=lambda i: (i.issue_date or i.created, i.number, i.created),
                      reverse=True)

    def numbers(self) -> set[str]:
        return {i.number for i in self.invoices.values() if i.number}

    def invoiced_logs(self, exclude_id: str = "") -> dict[str, list[str]]:
        """Log key -> invoice numbers it was billed on (exported invoices only)."""
        out: dict[str, list[str]] = {}
        for inv in self.invoices.values():
            if inv.id == exclude_id or inv.status == "draft":
                continue
            for ref in inv.log_refs:
                out.setdefault(ref.get("key", ""), []).append(inv.number)
        return out


# ---- invoice numbers ------------------------------------------------------------------------------------
DEFAULT_NUMBER_FORMAT = "{YYYY}-{MM}-{DD}-{NN}"
_COUNTER = re.compile(r"\{(N+)\}")


def number_format_ok(fmt: str) -> bool:
    return bool(_COUNTER.search(fmt or ""))


def reset_period(fmt: str) -> str:
    if "{DD}" in fmt:
        return "day"
    if "{MM}" in fmt:
        return "month"
    if "{YYYY}" in fmt or "{YY}" in fmt:
        return "year"
    return "never"


def period_key(fmt: str, day: dt.date) -> str:
    return {"day": day.isoformat(), "month": f"{day:%Y-%m}", "year": f"{day:%Y}", "never": "all"}[reset_period(fmt)]


def format_number(fmt: str, day: dt.date, n: int) -> str:
    fmt = fmt if number_format_ok(fmt) else DEFAULT_NUMBER_FORMAT
    out = fmt.replace("{YYYY}", f"{day:%Y}").replace("{YY}", f"{day:%y}").replace("{MM}", f"{day:%m}") \
        .replace("{DD}", f"{day:%d}")
    return _COUNTER.sub(lambda m: f"{n:0{len(m.group(1))}d}", out)


# ---- app settings ------------------------------------------------------------------------------------
@dataclass
class Settings:
    setup_done: bool = False
    use_docket_timesheets: bool = True
    use_docket_invoices: bool = True
    use_standalone: bool = True
    theme: str = "system"                # system | light | dark
    check_updates: bool = True
    skipped_version: str = ""
    logs_dir: str = ""                   # "" = Docket's folder from shared.json
    backup_dir: str = ""
    last_backup: str = ""
    last_profile: str = ""
    last_export_dir: str = ""
    open_pdf: bool = False
    open_folder: bool = True
    mode: str = "invoice"                # timesheet | invoice
    # table defaults
    time_format: str = "hms"
    clock: str = "24"
    show_seconds: bool = False
    rounding: str = "off"
    round_each_row: bool = False
    round_grand_once: bool = False
    layout: str = "sections"
    category_summary: bool = True
    columns: list = field(default_factory=default_columns)
    # invoices
    number_format: str = DEFAULT_NUMBER_FORMAT
    counters: dict = field(default_factory=dict)          # period key -> last number used
    currency: str = "CAD"
    terms_days: int = 30
    # window
    zoom: str = "fit"
    window_geometry: str = ""
    splitter_state: str = ""

    @classmethod
    def load(cls, folder: Path) -> "Settings":
        s = _from_dict(cls, _read_json(folder / "settings.json", {}))
        s.columns = normalise_columns(s.columns)
        s.theme = s.theme if s.theme in ("system", "light", "dark") else "system"
        s.mode = s.mode if s.mode in ("timesheet", "invoice") else "invoice"
        if not number_format_ok(s.number_format):
            s.number_format = DEFAULT_NUMBER_FORMAT
        return s

    def save(self, folder: Path) -> None:
        _write_json(folder / "settings.json", asdict(self))

    def table_options(self) -> TableOptions:
        return TableOptions(self.time_format, self.clock, self.show_seconds, self.rounding, self.round_each_row,
                            self.round_grand_once, self.layout, self.category_summary,
                            normalise_columns(self.columns))

    @property
    def uses_docket(self) -> bool:
        return self.use_docket_timesheets or self.use_docket_invoices

    @property
    def uses_invoices(self) -> bool:
        return self.use_docket_invoices or self.use_standalone

    @property
    def uses_timesheets(self) -> bool:
        return self.use_docket_timesheets

    # ---- numbering
    def next_number(self, day: dt.date, used: set[str]) -> tuple[int, str]:
        key = period_key(self.number_format, day)
        n = int(self.counters.get(key, 0)) + 1
        text = format_number(self.number_format, day, n)
        while text in used:
            n += 1
            text = format_number(self.number_format, day, n)
        return n, text

    def commit_number(self, day: dt.date, n: int) -> None:
        key = period_key(self.number_format, day)
        self.counters[key] = max(int(self.counters.get(key, 0)), n)

    def set_next(self, day: dt.date, n: int) -> None:
        """'Continuing from another invoicing tool': the next invoice gets number n."""
        self.counters[period_key(self.number_format, day)] = max(0, n - 1)


# ---- the data folder as a whole ------------------------------------------------------------------------------
class Data:
    def __init__(self, folder: Path | None = None):
        self.folder = folder or data_dir()
        self.folder.mkdir(parents=True, exist_ok=True)
        self.images = self.folder / "images"
        self.images.mkdir(exist_ok=True)
        self.settings = Settings.load(self.folder)
        self.profiles: list[Profile] = [Profile.from_dict(d) for d in
                                        _read_json(self.folder / "profiles.json", {}).get("profiles", [])]
        if not self.profiles:
            self.profiles = [Profile()]
        self.clients: list[Client] = [_from_dict(Client, d) for d in
                                      _read_json(self.folder / "clients.json", {}).get("clients", [])]
        self.items: list[SavedItem] = [_from_dict(SavedItem, d) for d in
                                       _read_json(self.folder / "items.json", {}).get("items", [])]
        self.invoices = InvoiceStore(self.folder)

    # ---- saving
    def save_settings(self) -> None:
        self.settings.save(self.folder)

    def save_profiles(self) -> None:
        _write_json(self.folder / "profiles.json", {"profiles": [p.to_dict() for p in self.profiles]})
        self.clean_images()

    def save_clients(self) -> None:
        _write_json(self.folder / "clients.json", {"clients": [asdict(c) for c in self.clients]})

    def save_items(self) -> None:
        _write_json(self.folder / "items.json", {"items": [asdict(i) for i in self.items]})

    # ---- profiles
    def profile(self, name: str = "") -> Profile:
        for p in self.profiles:
            if p.name == (name or self.settings.last_profile):
                return p
        return self.profiles[0]

    def unique_profile_name(self, base: str) -> str:
        names = {p.name for p in self.profiles}
        if base not in names:
            return base
        i = 2
        while f"{base} ({i})" in names:
            i += 1
        return f"{base} ({i})"

    def replace_profile(self, old_name: str, profile: Profile) -> None:
        for i, p in enumerate(self.profiles):
            if p.name == old_name:
                if profile.name != old_name:
                    profile.name = self.unique_profile_name(profile.name.strip() or "Profile")
                self.profiles[i] = profile
                break
        else:
            profile.name = self.unique_profile_name(profile.name.strip() or "Profile")
            self.profiles.append(profile)
        self.save_profiles()

    def delete_profile(self, name: str) -> None:
        self.profiles = [p for p in self.profiles if p.name != name] or [Profile()]
        self.save_profiles()

    # ---- clients
    def client(self, cid: str) -> Client | None:
        return next((c for c in self.clients if c.id == cid), None)

    def client_for_label(self, label: str) -> Client | None:
        return next((c for c in self.clients if c.matches(label)), None)

    def upsert_client(self, client: Client) -> None:
        for i, c in enumerate(self.clients):
            if c.id == client.id:
                self.clients[i] = client
                break
        else:
            self.clients.append(client)
        self.clients.sort(key=lambda c: c.display.lower())
        self.save_clients()

    def delete_client(self, cid: str) -> None:
        self.clients = [c for c in self.clients if c.id != cid]
        self.save_clients()

    def category_names(self) -> list[str]:
        """Every category with a rate, across all clients (names only, for shared.json)."""
        seen: dict[str, str] = {}
        for c in self.clients:
            for name in c.rates:
                if name.strip():
                    seen.setdefault(category_key(name), name.strip())
        return sorted(seen.values(), key=str.lower)

    # ---- images
    def image_path(self, name: str) -> Path | None:
        if not name:
            return None
        p = self.images / name
        return p if p.exists() else None

    def import_image(self, source: Path) -> str:
        name = f"{new_id()}{source.suffix.lower()}"
        shutil.copyfile(source, self.images / name)
        return name

    def clean_images(self) -> None:
        used = {n for p in self.profiles for n in (p.logo, p.watermark) if n}
        for f in self.images.iterdir():
            if f.is_file() and f.name not in used:
                try:
                    f.unlink()
                except OSError:
                    pass

    # ---- sharing a profile (one file with its images inside)
    def export_profile(self, name: str, dest: Path) -> None:
        p = self.profile(name)
        data = {"docket_ledger_profile": 1, "profile": p.to_dict(), "images": {}}
        for img in (p.logo, p.watermark):
            path = self.image_path(img)
            if path:
                data["images"][img] = base64.b64encode(path.read_bytes()).decode("ascii")
        _write_json(dest, data)

    def import_profile(self, source: Path) -> Profile:
        data = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "profile" not in data:
            raise ValueError("This file isn't a Docket Ledger profile.")
        p = Profile.from_dict(data["profile"])
        images = data.get("images") or {}
        for attr in ("logo", "watermark"):
            old = getattr(p, attr)
            if old and old in images:
                new = f"{new_id()}{Path(old).suffix.lower()}"
                (self.images / new).write_bytes(base64.b64decode(images[old]))
                setattr(p, attr, new)
            else:
                setattr(p, attr, "")
        p.name = self.unique_profile_name(p.name)
        self.profiles.append(p)
        self.save_profiles()
        return p

    # ---- backups
    def backup(self, dest_dir: Path | None = None, keep: int = 30) -> Path | None:
        """Zips the data folder into the backup folder (one zip per day, the newest `keep` kept)."""
        target = dest_dir or (Path(self.settings.backup_dir) if self.settings.backup_dir else None)
        if target is None:
            return None
        target = target / "Docket Ledger backups"
        target.mkdir(parents=True, exist_ok=True)
        out = target / f"DocketLedger-backup-{dt.date.today():%Y-%m-%d}.zip"
        tmp = out.with_suffix(".tmp")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for f in self.folder.rglob("*"):
                if f.is_file() and not f.name.endswith(".tmp"):
                    z.write(f, f.relative_to(self.folder))
        tmp.replace(out)
        old = sorted(target.glob("DocketLedger-backup-*.zip"))[:-keep]
        for f in old:
            try:
                f.unlink()
            except OSError:
                pass
        self.settings.last_backup = dt.date.today().isoformat()
        self.save_settings()
        return out
