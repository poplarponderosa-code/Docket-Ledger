"""The timesheet being prepared: editable rows, columns, rounding, totals and categories.

No Qt in here. Edits only change what goes into the PDF; log files are never written to.

Rounding rule (the same for timesheets and invoices, so they always agree):
  * "Round each row" on: every row is rounded, totals add up the rounded rows.
  * Otherwise each category's time is rounded once, and totals add up the rounded categories.
    (A log without categories is one category, so its total is simply rounded once.)
"""
from __future__ import annotations

import copy
import datetime as dt
from dataclasses import dataclass, field

from .logs import LogRow, TimeLog
from .timefmt import duration_header, fmt_date, fmt_date_range, fmt_duration, fmt_timestamp, round_seconds

COLUMN_NAMES = {
    "checklist": "Checklist",
    "step": "Step",
    "category": "Category",
    "start": "Start",
    "end": "End",
    "duration": "Duration",
    "limit": "Limit",
    "done": "Done",
}
COLUMN_ALIGN = {"duration": "right", "limit": "right", "done": "center"}
FLEX_COLUMNS = {"step", "checklist"}
NO_CATEGORY_LABEL = "General"


def default_columns() -> list[dict]:
    shown = {"checklist", "step", "category", "start", "end", "duration"}
    return [{"key": k, "label": name, "visible": k in shown} for k, name in COLUMN_NAMES.items()]


def normalise_columns(columns: list[dict] | None) -> list[dict]:
    """Keeps a saved column list valid: every known column once, in the saved order."""
    out, seen = [], set()
    for c in columns or []:
        k = c.get("key")
        if k in COLUMN_NAMES and k not in seen:
            out.append({"key": k, "label": str(c.get("label") or COLUMN_NAMES[k]),
                        "visible": bool(c.get("visible", True))})
            seen.add(k)
    defaults = default_columns()
    for i, c in enumerate(defaults):
        if c["key"] not in seen:
            if columns and c["key"] != "category":
                c["visible"] = False
            # put new columns next to where they belong by default
            before = defaults[i - 1]["key"] if i else None
            idx = next((j + 1 for j, o in enumerate(out) if o["key"] == before), len(out))
            out.insert(idx, c)
            seen.add(c["key"])
    return out


def category_key(name: str) -> str:
    return (name or "").strip().lower()


def category_label(name: str) -> str:
    name = (name or "").strip()
    return name[:1].upper() + name[1:] if name else NO_CATEGORY_LABEL


# ---- editable rows ----------------------------------------------------------------
@dataclass
class EditRow:
    step: str = ""
    category: str = ""
    start: dt.datetime | None = None
    end: dt.datetime | None = None
    override: int | None = None          # a duration typed in directly, in seconds
    limit: str = ""
    done: str = ""
    included: bool = True
    orig: LogRow | None = None           # None = a row added by hand

    @classmethod
    def from_log(cls, r: LogRow) -> "EditRow":
        return cls(r.step, r.category, r.start, r.end, None, r.limit, r.done, True, r)

    @property
    def seconds(self) -> int:
        if self.override is not None:
            return self.override
        if self.orig is not None and self.start == self.orig.start and self.end == self.orig.end:
            return self.orig.seconds            # Docket's own duration (the timer may have been paused)
        if self.start and self.end and self.end >= self.start:
            return int((self.end - self.start).total_seconds())
        return 0

    @property
    def manual(self) -> bool:
        return self.orig is None

    def edited(self, field_name: str) -> bool:
        if self.orig is None:
            return True
        if field_name == "duration":
            return self.override is not None or self.seconds != self.orig.seconds
        if field_name == "included":
            return not self.included
        return getattr(self, field_name) != getattr(self.orig, field_name)


@dataclass
class LogEdits:
    key: str
    rows: list[EditRow] = field(default_factory=list)

    @classmethod
    def from_log(cls, log: TimeLog) -> "LogEdits":
        return cls(log.key, [EditRow.from_log(r) for r in log.rows])

    def reset(self, log: TimeLog) -> None:
        self.rows = [EditRow.from_log(r) for r in log.rows]

    @property
    def changed(self) -> bool:
        if any(r.manual for r in self.rows):
            return True
        return any(r.edited(f) for r in self.rows
                   for f in ("step", "category", "start", "end", "duration", "limit", "done", "included"))


# ---- options ------------------------------------------------------------------------
@dataclass
class TableOptions:
    time_format: str = "hms"             # hms | hm | decimal
    clock: str = "24"                    # 24 | 12
    show_seconds: bool = False           # in the Start and End columns
    rounding: str = "off"
    round_each_row: bool = False
    round_grand_once: bool = False       # combined logs: grand total from all time at once, not the subtotals
    layout: str = "sections"             # combined logs: sections | single
    category_summary: bool = True        # "Time by category" table when steps have categories
    columns: list[dict] = field(default_factory=default_columns)

    def copy(self) -> "TableOptions":
        return copy.deepcopy(self)

    @property
    def per_row(self) -> bool:
        return self.round_each_row and self.rounding != "off"


def billed_seconds(rows: list[EditRow], opts: TableOptions) -> int:
    """Total time after rounding, by the rule at the top of this file."""
    if opts.per_row:
        return sum(round_seconds(r.seconds, opts.rounding) for r in rows)
    return sum(round_seconds(s, opts.rounding) for s in category_raw(rows).values())


def category_raw(rows: list[EditRow]) -> dict[str, int]:
    """Raw seconds per category key, in order of first appearance."""
    out: dict[str, int] = {}
    for r in rows:
        k = category_key(r.category)
        out[k] = out.get(k, 0) + r.seconds
    return out


def category_billed(rows: list[EditRow], opts: TableOptions) -> list[tuple[str, str, int, int]]:
    """[(key, label, raw seconds, billed seconds)] per category, in order of first appearance,
    with the uncategorised group last."""
    labels: dict[str, str] = {}
    raw: dict[str, int] = {}
    billed: dict[str, int] = {}
    for r in rows:
        k = category_key(r.category)
        labels.setdefault(k, category_label(r.category))
        raw[k] = raw.get(k, 0) + r.seconds
        if opts.per_row:
            billed[k] = billed.get(k, 0) + round_seconds(r.seconds, opts.rounding)
    if not opts.per_row:
        billed = {k: round_seconds(v, opts.rounding) for k, v in raw.items()}
    keys = sorted(raw, key=lambda k: (k == "",))
    return [(k, labels[k], raw[k], billed[k]) for k in keys]


# ---- what the PDF is built from ----------------------------------------------------------
@dataclass
class Column:
    key: str
    label: str
    align: str = "left"


@dataclass
class Section:
    heading: str                         # "" for a single log
    subheading: str
    rows: list[list[str]]
    total_label: str
    total: str


@dataclass
class DocSpec:
    title: str
    description: str
    date_range: str
    generated: str
    columns: list[Column]
    sections: list[Section]
    grand_total: str | None              # only for combined logs shown as sections
    actual_seconds: int
    billed_seconds: int
    categories: list[tuple[str, str]] = field(default_factory=list)   # (label, time) for "Time by category"
    category_total: str = ""


def _done_text(value: str) -> str:
    v = value.strip().lower()
    if v in ("yes", "y", "true", "1", "done"):
        return "Yes"
    if v in ("no", "n", "false", "0"):
        return "No"
    return value


def _cell(key: str, log: TimeLog, row: EditRow, secs: int, opts: TableOptions) -> str:
    if key == "checklist":
        return log.title
    if key == "step":
        return row.step
    if key == "category":
        return row.category
    if key == "start":
        return fmt_timestamp(row.start, opts.clock, opts.show_seconds)
    if key == "end":
        return fmt_timestamp(row.end, opts.clock, opts.show_seconds)
    if key == "duration":
        return fmt_duration(secs, opts.time_format)
    if key == "limit":
        return row.limit
    if key == "done":
        return _done_text(row.done)
    return ""


def _dates(log: TimeLog, rows: list[EditRow]) -> list[dt.date]:
    stamps = [t for r in rows for t in (r.start, r.end) if t]
    if not stamps:
        stamps = [t for t in (log.started, log.finished) if t]
    return [t.date() for t in stamps]


def visible_columns(opts: TableOptions, combined_single: bool, has_categories: bool = True) -> list[Column]:
    cols = []
    for c in normalise_columns(opts.columns):
        if not c["visible"]:
            continue
        if c["key"] == "checklist" and not combined_single:
            continue
        if c["key"] == "category" and not has_categories:
            continue
        label = c["label"]
        if c["key"] == "duration" and label == COLUMN_NAMES["duration"]:
            label = duration_header(opts.time_format)
        cols.append(Column(c["key"], label, COLUMN_ALIGN.get(c["key"], "left")))
    if not cols:
        cols.append(Column("step", COLUMN_NAMES["step"]))
    return cols


def build_spec(entries: list[tuple[TimeLog, LogEdits]], title: str, description: str,
               opts: TableOptions, today: dt.date | None = None) -> DocSpec:
    """Everything a timesheet shows, worked out from the logs, the edits and the options."""
    today = today or dt.date.today()
    combined = len(entries) > 1
    single_table = combined and opts.layout == "single"
    rnd, per_row = opts.rounding, opts.per_row
    entries = sorted(entries, key=lambda e: e[0].sort_time) if combined else list(entries)

    included = [(log, [r for r in edits.rows if r.included]) for log, edits in entries]
    all_rows = [r for _, rows in included for r in rows]
    has_categories = any(r.category.strip() for r in all_rows)
    columns = visible_columns(opts, single_table, has_categories)
    fmt = opts.time_format

    def shown(r: EditRow) -> int:
        return round_seconds(r.seconds, rnd) if per_row else r.seconds

    all_dates: list[dt.date] = []
    for log, rows in included:
        all_dates += _dates(log, rows)
    actual = sum(r.seconds for r in all_rows)

    sections: list[Section] = []
    grand: str | None = None
    if single_table or not combined:
        rows_out = [[_cell(c.key, log, r, shown(r), opts) for c in columns] for log, rows in included for r in rows]
        billed = billed_seconds(all_rows, opts)
        sections.append(Section("", "", rows_out, "Total", fmt_duration(billed, fmt)))
    else:
        subtotals = []
        for log, rows in included:
            sub = billed_seconds(rows, opts)
            subtotals.append(sub)
            dates = _dates(log, rows)
            sections.append(Section(log.title, fmt_date_range(min(dates), max(dates)) if dates else "",
                                    [[_cell(c.key, log, r, shown(r), opts) for c in columns] for r in rows],
                                    "Subtotal", fmt_duration(sub, fmt)))
        billed = billed_seconds(all_rows, opts) if opts.round_grand_once else sum(subtotals)
        grand = fmt_duration(billed, fmt)

    cats: list[tuple[str, str]] = []
    cat_total = ""
    if opts.category_summary and has_categories:
        per_cat = category_billed(all_rows, opts)
        cats = [(label, fmt_duration(b, fmt)) for _, label, _, b in per_cat]
        cat_total = fmt_duration(sum(b for _, _, _, b in per_cat), fmt)

    date_range = fmt_date_range(min(all_dates), max(all_dates)) if all_dates else ""
    return DocSpec(title=title, description=description, date_range=date_range,
                   generated=fmt_date(today), columns=columns, sections=sections, grand_total=grand,
                   actual_seconds=actual, billed_seconds=billed, categories=cats, category_total=cat_total)
