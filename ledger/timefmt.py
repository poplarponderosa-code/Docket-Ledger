"""Durations, dates and rounding. No Qt in here."""
from __future__ import annotations

import datetime as dt
import math
import re

# ---- time formats ---------------------------------------------------------------
TIME_FORMATS = [("hms", "hh:mm:ss"), ("hm", "hh:mm"), ("decimal", "Decimal hours")]

ROUNDING = [
    ("off", "Off"),
    ("nearest6", "Nearest 6 min"),
    ("nearest15", "Nearest 15 min"),
    ("up15", "Up to 15 min"),
    ("up30", "Up to 30 min"),
]

TIMESTAMP = "%Y-%m-%d %H:%M:%S"


def fmt_duration(seconds: float, mode: str = "hms") -> str:
    """01:47:12 / 01:47 / 1.79"""
    seconds = max(0, int(round(seconds)))
    if mode == "decimal":
        return f"{seconds / 3600:.2f}"
    if mode == "hm":
        minutes = int(math.floor(seconds / 60 + 0.5))
        return f"{minutes // 60:02d}:{minutes % 60:02d}"
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def duration_header(mode: str) -> str:
    return "Hours" if mode == "decimal" else "Duration"


def fmt_timestamp(value: dt.datetime | None, clock: str = "24", seconds: bool = False) -> str:
    """The Start and End columns in the PDF."""
    if value is None:
        return ""
    if clock == "12":
        t = value.strftime("%I:%M:%S %p" if seconds else "%I:%M %p").lstrip("0")
    else:
        t = value.strftime("%H:%M:%S" if seconds else "%H:%M")
    return f"{value:%Y-%m-%d} {t}"


def fmt_date(value: dt.date) -> str:
    return f"{value:%b} {value.day}, {value.year}"


def fmt_date_range(first: dt.date | None, last: dt.date | None) -> str:
    if first is None:
        return ""
    if last is None or last == first:
        return fmt_date(first)
    if first.year == last.year and first.month == last.month:
        return f"{first:%b} {first.day}–{last.day}, {first.year}"
    if first.year == last.year:
        return f"{first:%b} {first.day} – {last:%b} {last.day}, {first.year}"
    return f"{fmt_date(first)} – {fmt_date(last)}"


# ---- parsing ----------------------------------------------------------------------
def parse_timestamp(text: str, base: dt.datetime | None = None) -> dt.datetime | None:
    """Reads what a person types into a Start or End cell.

    Accepts "2026-11-21 23:44:20", "2026-11-21 23:44", "23:44", "11:44 PM" (a time alone
    keeps the date of `base`). Returns None for an empty cell; raises ValueError otherwise.
    """
    text = " ".join(text.strip().split())
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %I:%M:%S %p", "%Y-%m-%d %I:%M %p",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(text.upper(), fmt)
        except ValueError:
            pass
    for fmt in ("%H:%M:%S", "%H:%M", "%I:%M:%S %p", "%I:%M %p", "%I:%M%p", "%I %p"):
        try:
            t = dt.datetime.strptime(text.upper(), fmt).time()
        except ValueError:
            continue
        day = (base or dt.datetime.now()).date()
        return dt.datetime.combine(day, t)
    raise ValueError(f"Can't read the time “{text}”. Use YYYY-MM-DD HH:MM:SS.")


_UNIT = re.compile(r"(\d+(?:\.\d+)?)\s*(h|hr|hrs|hour|hours|m|min|mins|minute|minutes|s|sec|secs|second|seconds)\b")


def parse_duration(text: str) -> int:
    """Reads a typed duration, in seconds.

    "1:30:00" (h:mm:ss), "1:30" (h:mm), "1.5" (hours), "90m", "2h 15m", "45s".
    """
    text = text.strip().lower()
    if not text:
        return 0
    if ":" in text:
        parts = text.split(":")
        if len(parts) not in (2, 3) or not all(p.strip().isdigit() for p in parts):
            raise ValueError(f"Can't read the duration “{text}”.")
        nums = [int(p) for p in parts]
        if len(nums) == 2:
            return nums[0] * 3600 + nums[1] * 60
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    matches = _UNIT.findall(text)
    if matches and _UNIT.sub("", text).strip() == "":
        total = 0.0
        for num, unit in matches:
            mult = 3600 if unit.startswith("h") else 60 if unit.startswith("m") else 1
            total += float(num) * mult
        return int(round(total))
    try:
        return int(round(float(text) * 3600))
    except ValueError:
        raise ValueError(f"Can't read the duration “{text}”. Try 1:30:00, 1.5 or 90m.") from None


def parse_log_duration(text: str) -> int | None:
    """Docket's own Duration column: m:ss, or h:mm:ss for long steps."""
    text = text.strip()
    if not text or text == "-":
        return None
    parts = text.split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    return None


# ---- rounding ---------------------------------------------------------------------
def round_seconds(seconds: float, mode: str) -> int:
    seconds = max(0, int(round(seconds)))
    if mode == "off" or not mode:
        return seconds
    step = {"nearest6": 360, "nearest15": 900, "up15": 900, "up30": 1800}.get(mode)
    if step is None:
        return seconds
    if mode.startswith("up"):
        return int(math.ceil(seconds / step) * step)
    return int(math.floor(seconds / step + 0.5) * step)
