"""Turns an invoice (plus any time logs on it) into lines and totals. No Qt in here."""
from __future__ import annotations

import csv
import datetime as dt
import io
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from .logs import TimeLog
from .model import DocSpec, LogEdits, TableOptions, category_billed
from .money import Line, Totals, compute, dec, fmt_money, fmt_number, hours_from_seconds
from .store import Client, Invoice, Profile
from .timefmt import fmt_date, fmt_date_range, parse_duration, round_seconds

KINDS = [("hours", "Hours"), ("qty", "Quantity"), ("fixed", "Fixed price")]


def rounding_options(inv: Invoice) -> TableOptions:
    return TableOptions(rounding=inv.rounding, round_each_row=inv.round_each_row, round_grand_once=True)


def ref_for(log: TimeLog, edits: LogEdits, opts: TableOptions) -> dict:
    """What an invoice remembers about a log, so it still adds up if the log file is deleted."""
    rows = [r for r in edits.rows if r.included]
    cats = {k: [label, raw] for k, label, raw, _ in category_billed(rows, opts)}
    return {"key": log.key, "path": str(log.path or ""), "title": log.title, "client": log.client,
            "finished": log.sort_time.isoformat(timespec="minutes"), "seconds": sum(r.seconds for r in rows),
            "categories": cats}


@dataclass
class CategoryTime:
    key: str
    label: str
    seconds: int                         # after rounding
    raw: int


def category_times(entries: list[tuple[TimeLog, LogEdits]], missing_refs: list[dict],
                   inv: Invoice) -> list[CategoryTime]:
    """Time per category across every log on the invoice, rounded once per category (or per row).

    Logs whose files have gone missing count with the totals the invoice saved for them."""
    opts = rounding_options(inv)
    rows = [r for _, e in entries for r in e.rows if r.included]
    out = {k: CategoryTime(k, label, billed, raw) for k, label, raw, billed in category_billed(rows, opts)}
    extra: dict[str, int] = {}
    for ref in missing_refs:
        for k, (label, raw) in (ref.get("categories") or {}).items():
            out.setdefault(k, CategoryTime(k, label, 0, 0)).raw += int(raw)
            extra[k] = extra.get(k, 0) + int(raw)
    for k, raw in extra.items():
        ct = out[k]
        ct.seconds = ct.seconds + round_seconds(raw, inv.rounding) if opts.per_row else \
            round_seconds(ct.raw, inv.rounding)
    return sorted(out.values(), key=lambda c: (c.key == "",))


def rate_for(inv: Invoice, client: Client | None, key: str, label: str) -> str:
    if str(inv.category_rates.get(key, "")).strip():
        return str(inv.category_rates[key])
    if client is not None:
        return client.rate_for(label if key else "")
    return ""


def log_lines(times: list[CategoryTime], inv: Invoice, client: Client | None, detail: str = "") -> list[Line]:
    lines = []
    for ct in times:
        price = dec(rate_for(inv, client, ct.key, ct.label), None)
        lines.append(Line("hours", ct.label, detail, ct.label, hours_from_seconds(ct.seconds), "h", price,
                          unpriced=price is None))
    return lines


def manual_lines(inv: Invoice) -> list[Line]:
    out = []
    for d in inv.lines:
        kind = d.get("kind", "hours")
        desc = str(d.get("description", "")).strip()
        if not desc and not str(d.get("price", "")).strip():
            continue
        qty = dec(d.get("qty"), Decimal(0)) if kind != "fixed" else Decimal(0)
        if kind == "hours" and isinstance(d.get("qty"), str) and ":" in d["qty"]:
            try:
                qty = hours_from_seconds(parse_duration(d["qty"]))
            except ValueError:
                qty = Decimal(0)
        price = dec(d.get("price"), None)
        unit = "h" if kind == "hours" else str(d.get("unit", "")).strip()
        out.append(Line(kind, desc or "Item", str(d.get("detail", "")), str(d.get("category", "")), qty, unit, price,
                        unpriced=price is None))
    return out


def enabled_taxes(inv: Invoice) -> list[tuple[str, Decimal]]:
    out = []
    for t in inv.taxes:
        if t.get("on"):
            rate = dec(t.get("rate"), None)
            if rate:
                out.append((str(t.get("name") or "Tax"), rate))
    return out


def totals(inv: Invoice, lines: list[Line]) -> Totals:
    return compute(lines, inv.currency, inv.discount_kind, inv.discount_value, enabled_taxes(inv))


def taxes_for_client(profile: Profile, client: Client | None, current: list | None = None) -> list[dict]:
    """The profile's tax lines, switched on where the client says so (or as they were on this invoice)."""
    was = {t.get("id"): t.get("on") for t in (current or [])}
    out = []
    for t in profile.taxes:
        on = was[t["id"]] if t["id"] in was else bool(client and t["id"] in client.taxes)
        out.append({"id": t["id"], "name": t["name"], "rate": t["rate"], "on": bool(on)})
    return out


def logs_detail(entries: list[tuple[TimeLog, LogEdits]], missing: list[dict]) -> str:
    titles = [lg.title for lg, _ in entries] + [r.get("title", "") for r in missing]
    dates = [lg.sort_time.date() for lg, _ in entries]
    for r in missing:
        try:
            dates.append(dt.datetime.fromisoformat(r.get("finished", "")).date())
        except ValueError:
            pass
    when = fmt_date_range(min(dates), max(dates)) if dates else ""
    if len(set(titles)) == 1 and titles:
        return f"{titles[0]} · {when}" if when else titles[0]
    return f"{len(titles)} checklists · {when}" if when else f"{len(titles)} checklists"


# ---- what the invoice PDF is built from ------------------------------------------------------------------
@dataclass
class InvoiceSpec:
    title: str
    number: str
    issue: str
    due: str
    terms: str
    client_name: str
    bill_to: str
    currency: str
    totals: Totals
    notes: str
    payment: str
    tax_number: str
    status: str = "draft"
    attachment: DocSpec | None = None
    rows: list[list[str]] = field(default_factory=list)


def terms_text(days: int) -> str:
    return "Due on receipt" if days <= 0 else f"Net {days}"


def build_invoice_spec(inv: Invoice, client: Client | None, profile: Profile, lines: list[Line],
                       number_text: str, attachment: DocSpec | None = None) -> InvoiceSpec:
    t = totals(inv, lines)
    snap = inv.client_snapshot if inv.status != "draft" and inv.client_snapshot else {}
    name = snap.get("name") or (client.name or client.label if client else "")
    bill = snap.get("bill_to") if snap else (client.bill_to if client else "")
    due = inv.due
    return InvoiceSpec(
        title=inv.title or "Invoice", number=number_text, issue=fmt_date(inv.issue),
        due=fmt_date(due) if due else "", terms=terms_text(inv.terms_days), client_name=name or "",
        bill_to=bill or "", currency=inv.currency, totals=t, notes=inv.notes, payment=profile.payment,
        tax_number=profile.tax_number, status=inv.status, attachment=attachment)


def line_cells(ln: Line, currency: str) -> tuple[str, str, str]:
    """(quantity, rate, amount) as printed."""
    if ln.kind == "fixed":
        return "", "", fmt_money(ln.amount, currency) if ln.price is not None else "Rate needed"
    qty = f"{fmt_number(ln.qty)} {ln.unit}".strip()
    if ln.price is None:
        return qty, "Rate needed", "—"
    return qty, fmt_money(ln.price, currency), fmt_money(ln.amount, currency)


def email_text(spec: InvoiceSpec, sender: str) -> str:
    name = sender.strip().split("\n")[0] if sender.strip() else ""
    amount = fmt_money(spec.totals.total, spec.currency, code=True)
    due = f", due {spec.due}" if spec.due else ""
    subject = f"Invoice {spec.number}" + (f" from {name}" if name else "")
    body = (f"Hi{(' ' + spec.client_name) if spec.client_name else ''},\n\n"
            f"Please find attached invoice {spec.number} for {amount}{due}.\n")
    if spec.payment.strip():
        body += f"\n{spec.payment.strip()}\n"
    body += f"\nThank you,\n{name}\n" if name else "\nThank you.\n"
    return f"Subject: {subject}\n\n{body}"


# ---- importing hours from another time tracker -----------------------------------------------------------------
def import_hours_csv(path: Path) -> list[dict]:
    """Reads a simple CSV (date, description, hours, category; other columns ignored) into invoice lines.

    Hours can be 1.5 or 1:30. Column names are matched loosely (task/item/notes, duration/time).
    """
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return []
    names = {n: n.strip().lower() for n in reader.fieldnames}

    def pick(*cands: str) -> str | None:
        for n, low in names.items():
            if low in cands:
                return n
        for n, low in names.items():
            if any(c in low for c in cands):
                return n
        return None

    c_desc = pick("description", "task", "item", "step", "notes", "project")
    c_hours = pick("hours", "duration", "time")
    c_cat = pick("category", "tag", "type")
    c_date = pick("date", "start date", "day")
    if c_hours is None:
        raise ValueError("The CSV needs an Hours (or Duration) column.")
    out = []
    for rec in reader:
        raw = (rec.get(c_hours) or "").strip()
        if not raw:
            continue
        try:
            secs = parse_duration(raw)
        except ValueError:
            continue
        desc = (rec.get(c_desc) or "").strip() if c_desc else ""
        date = (rec.get(c_date) or "").strip() if c_date else ""
        out.append({"kind": "hours", "description": desc or "Work", "detail": date,
                    "category": (rec.get(c_cat) or "").strip() if c_cat else "",
                    "qty": str(hours_from_seconds(secs)), "unit": "h", "price": ""})
    return out
