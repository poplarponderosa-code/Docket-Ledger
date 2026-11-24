"""Finds and reads Docket time logs. No Qt in here.

Docket writes each log twice with the same name: a .txt (header with checklist, client,
template, description, started, finished) and a .csv (one row per step). They're read as one
log: rows come from the CSV when there is one, the header from the TXT.

Durations come from Docket's own Duration column (the timer can be paused, so Start to End
isn't always the time worked). Start and End are only used when a duration is missing.
"""
from __future__ import annotations

import csv
import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path

from .timefmt import TIMESTAMP, parse_log_duration

EXTENSIONS = (".txt", ".csv")
NO_CATEGORY = ""


@dataclass
class LogRow:
    step: str
    category: str
    start: dt.datetime | None
    end: dt.datetime | None
    seconds: int
    limit: str = ""
    done: str = ""


@dataclass
class TimeLog:
    key: str                      # the shared file name, without extension
    folder: Path
    txt: Path | None = None
    csv: Path | None = None
    title: str = ""
    description: str = ""
    client: str = ""              # Docket's client label (e.g. "Acme"), never contact details
    template: str = ""
    started: dt.datetime | None = None
    finished: dt.datetime | None = None
    rows: list[LogRow] = field(default_factory=list)
    warning: str = ""
    mtime: float = 0.0

    @property
    def total_seconds(self) -> int:
        return sum(r.seconds for r in self.rows)

    @property
    def sort_time(self) -> dt.datetime:
        when = self.finished or self.started
        if when is None:
            stamps = [r.end or r.start for r in self.rows if r.end or r.start]
            when = max(stamps) if stamps else None
        return when or dt.datetime.fromtimestamp(self.mtime)

    @property
    def paths(self) -> list[Path]:
        return [p for p in (self.csv, self.txt) if p is not None]

    @property
    def path(self) -> Path | None:
        return self.paths[0] if self.paths else None

    def categories(self) -> list[str]:
        out: list[str] = []
        seen = set()
        for r in self.rows:
            k = r.category.strip().lower()
            if k not in seen:
                seen.add(k)
                out.append(r.category.strip())
        return out


def _ts(text: str) -> dt.datetime | None:
    text = (text or "").strip()
    if not text or text == "-":
        return None
    try:
        return dt.datetime.strptime(text, TIMESTAMP)
    except ValueError:
        try:
            return dt.datetime.fromisoformat(text)
        except ValueError:
            return None


def _clean(value: str) -> str:
    value = (value or "").strip()
    return "" if value == "-" else value


def _seconds(duration: str, minutes: str, start: dt.datetime | None, end: dt.datetime | None) -> int:
    secs = parse_log_duration(duration or "")
    if secs is not None:
        return secs
    if (minutes or "").strip():
        try:
            return int(round(float(minutes) * 60))
        except ValueError:
            pass
    if start and end and end >= start:
        return int((end - start).total_seconds())
    return 0


def _drop_total(rows: list[LogRow], steps: list[str]) -> list[LogRow]:
    # Docket ends each log with a "Total" row; Ledger works totals out itself.
    if steps and steps[-1].strip().lower() == "total":
        return rows[:-1]
    return rows


def read_txt(path: Path, log: TimeLog) -> list[LogRow]:
    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    header: dict[str, str] = {}
    i, last_key = 0, ""
    while i < len(lines) and "|" not in lines[i]:
        raw = lines[i]
        line = raw.strip()
        if line and not line.startswith("#"):
            if raw[:1] in (" ", "\t") and last_key == "description":
                header["description"] += "\n" + line          # description continues on indented lines
            elif ":" in line:
                k, v = line.split(":", 1)
                last_key = k.strip().lower()
                header[last_key] = v.strip()
        i += 1
    log.title = log.title or header.get("checklist", "")
    log.description = header.get("description", log.description)
    log.client = log.client or header.get("client", "")
    log.template = log.template or header.get("template", "")
    log.started = log.started or _ts(header.get("started", ""))
    log.finished = log.finished or _ts(header.get("finished", ""))

    rows: list[LogRow] = []
    steps: list[str] = []
    cols: list[str] = []
    for line in lines[i:]:
        if not line.strip():
            if cols:
                break                       # end of the step table ("By category" comes after)
            continue
        if "|" not in line:
            continue
        cells = [c.strip() for c in line.split("|")]
        if not cols:
            cols = [c.lower() for c in cells]
            continue
        rec = dict(zip(cols, cells))
        step = rec.get("step", "")
        steps.append(step)
        start, end = _ts(rec.get("start", "")), _ts(rec.get("end", ""))
        rows.append(LogRow(step, _clean(rec.get("category", "")), start, end,
                           _seconds(rec.get("duration", ""), "", start, end),
                           _clean(rec.get("limit", "")), _clean(rec.get("done", ""))))
    return _drop_total(rows, steps)


def read_csv(path: Path, log: TimeLog) -> list[LogRow]:
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return []
        reader.fieldnames = [n.strip().lower() for n in reader.fieldnames]
        if "step" not in reader.fieldnames:
            raise ValueError("not a Docket time log (no Step column)")
        rows: list[LogRow] = []
        steps: list[str] = []
        for rec in reader:
            rec = {k: (v or "") for k, v in rec.items() if k}
            if not any(v.strip() for v in rec.values()):
                continue
            if not log.title and rec.get("checklist", "").strip():
                log.title = rec["checklist"].strip()
            if not log.client and rec.get("client", "").strip():
                log.client = rec["client"].strip()
            if not log.template and rec.get("template", "").strip():
                log.template = rec["template"].strip()
            step = rec.get("step", "").strip()
            steps.append(step)
            start, end = _ts(rec.get("start", "")), _ts(rec.get("end", ""))
            rows.append(LogRow(step, _clean(rec.get("category", "")), start, end,
                               _seconds(rec.get("duration", ""), rec.get("minutes", ""), start, end),
                               _clean(rec.get("limit", "")), _clean(rec.get("done", ""))))
        if steps and steps[-1].lower() == "total" and rows:
            total = rows[-1]
            log.started = log.started or total.start
            log.finished = log.finished or total.end
    return _drop_total(rows, steps)


_STAMP = re.compile(r"[ _]\d{4}-\d{2}-\d{2}[ _]\d{4}$")


def title_from_key(key: str) -> str:
    return _STAMP.sub("", key).replace("_", " ").strip() or key


def read_log(key: str, folder: Path, txt: Path | None, csv_path: Path | None) -> TimeLog:
    log = TimeLog(key=key, folder=folder, txt=txt, csv=csv_path)
    log.mtime = max((p.stat().st_mtime for p in log.paths if p.exists()), default=0.0)
    problems = []
    txt_rows: list[LogRow] = []
    if txt is not None:
        try:
            txt_rows = read_txt(txt, log)
        except Exception as e:      # noqa: BLE001 - a bad file shows a warning, never crashes the list
            problems.append(f"TXT: {e}")
    if csv_path is not None:
        try:
            log.rows = read_csv(csv_path, log)
        except Exception as e:      # noqa: BLE001
            problems.append(f"CSV: {e}")
    if not log.rows:
        log.rows = txt_rows
    if not log.title:
        log.title = title_from_key(key)
    if not log.rows and not problems:
        problems.append("No steps found in this log.")
    log.warning = "; ".join(problems)
    return log


def pair_files(folder: Path) -> dict[str, dict[str, Path]]:
    pairs: dict[str, dict[str, Path]] = {}
    try:
        entries = list(folder.iterdir())
    except OSError:
        return pairs
    for p in entries:
        try:
            if p.is_file() and p.suffix.lower() in EXTENSIONS:
                pairs.setdefault(p.stem, {})[p.suffix.lower()] = p
        except OSError:
            continue
    return pairs


def _looks_like_docket_txt(path: Path) -> bool:
    try:
        with path.open(encoding="utf-8-sig", errors="replace") as f:
            return f.readline().strip().lower().startswith("# docket time log")
    except OSError:
        return False


def scan(folder: Path | None) -> list[TimeLog]:
    """Every log in the folder, newest first."""
    if folder is None or not folder.is_dir():
        return []
    logs = []
    for stem, files in pair_files(folder).items():
        txt, csv_path = files.get(".txt"), files.get(".csv")
        if txt is not None and not _looks_like_docket_txt(txt):
            txt = None
        if txt is None and csv_path is None:
            continue
        lg = read_log(stem, folder, txt, csv_path)
        if lg.rows or lg.txt is not None:
            logs.append(lg)
    logs.sort(key=lambda lg: lg.sort_time, reverse=True)
    return logs


def log_for_path(path: Path) -> TimeLog | None:
    """The log a .txt or .csv belongs to (used by --open from Docket)."""
    path = Path(path)
    if not path.exists() or path.suffix.lower() not in EXTENSIONS:
        return None
    files = pair_files(path.parent).get(path.stem, {})
    return read_log(path.stem, path.parent, files.get(".txt"), files.get(".csv"))
