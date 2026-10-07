"""Deterministic parser for dates, times and reminder offsets.

Conventions (documented because they are interpretation choices):
  * "tomorrow"/"today"/"day after tomorrow" are relative to `today`.
  * A bare weekday ("Friday") = the next such weekday, today included.
  * "next <weekday>" = the first such weekday strictly AFTER today.
  * "Month D" with no year = the next occurrence on/after today.
  * "DD/MM/YYYY" is day-first.
  * "at 3" (no am/pm) is ambiguous: 1-6 -> PM, 7-11 -> AM, 12 -> noon. A
    warning is attached so the user confirms.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List, Optional, Tuple

Span = Tuple[int, int]

WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
            "friday": 4, "saturday": 5, "sunday": 6}
MONTHS = {"january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
          "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
          "august": 8, "aug": 8, "september": 9, "sept": 9, "sep": 9,
          "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12}
_MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))
_WEEKDAY_RE = "|".join(WEEKDAYS)
UNIT_MINUTES = {"minute": 1, "min": 1, "hour": 60, "hr": 60, "day": 1440, "week": 10080}


@dataclass
class DateResult:
    value: Optional[date] = None
    span: Optional[Span] = None
    relative: bool = False
    kind: str = "none"
    error: Optional[str] = None
    warnings: List[str] = field(default_factory=list)


@dataclass
class TimeResult:
    value: Optional[str] = None
    span: Optional[Span] = None
    warnings: List[str] = field(default_factory=list)


def _build(y: int, m: int, d: int, label: str):
    try:
        return date(y, m, d), None
    except ValueError:
        return None, f"'{label}' is not a valid calendar date."


def _infer_year(month: int, day: int, today: date, label: str):
    d, err = _build(today.year, month, day, label)
    if d and d < today:
        d, err = _build(today.year + 1, month, day, label)
    return d, err


def parse_date(text: str, today: date) -> DateResult:
    I = re.I
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    if m:
        d, err = _build(int(m[1]), int(m[2]), int(m[3]), m[0])
        return DateResult(d, m.span(), False, "iso", err)

    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", text)
    if m:
        d, err = _build(int(m[3]), int(m[2]), int(m[1]), m[0])
        return DateResult(d, m.span(), False, "numeric", err, ["Numeric dates are read as DD/MM/YYYY."])

    m = re.search(rf"\b({_MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b", text, I)
    if m:
        mo, day = MONTHS[m[1].lower()], int(m[2])
        d, err = _build(int(m[3]), mo, day, m[0]) if m[3] else _infer_year(mo, day, today, m[0])
        return DateResult(d, m.span(), False, "month_day", err)

    m = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH_RE})\b\.?(?:,?\s+(\d{{4}}))?", text, I)
    if m:
        mo, day = MONTHS[m[2].lower()], int(m[1])
        d, err = _build(int(m[3]), mo, day, m[0]) if m[3] else _infer_year(mo, day, today, m[0])
        return DateResult(d, m.span(), False, "day_month", err)

    m = re.search(r"\bday after tomorrow\b", text, I)
    if m:
        return DateResult(today + timedelta(days=2), m.span(), True, "relative")
    m = re.search(r"\btomorrow\b", text, I)
    if m:
        return DateResult(today + timedelta(days=1), m.span(), True, "relative")
    m = re.search(r"\b(today|tonight)\b", text, I)
    if m:
        return DateResult(today, m.span(), True, "relative")

    m = re.search(r"\bin\s+(\d+)\s+(day|week)s?\b", text, I)
    if m:
        n = int(m[1]) * (7 if m[2].lower() == "week" else 1)
        return DateResult(today + timedelta(days=n), m.span(), True, "relative")

    m = re.search(rf"\b(?:(next|this|coming|upcoming)\s+)?({_WEEKDAY_RE})\b", text, I)
    if m:
        wd = WEEKDAYS[m[2].lower()]
        delta = (wd - today.weekday()) % 7
        warns: List[str] = []
        if m[1] and m[1].lower() == "next":
            delta = delta or 7
            warns.append(f"'next {m[2].lower()}' was interpreted as the first {m[2].lower()} after today.")
        return DateResult(today + timedelta(days=delta), m.span(), True, "weekday", None, warns)

    return DateResult()


def _to24(hour: int, minute: int, meridiem: str) -> Optional[str]:
    if not (1 <= hour <= 12 and 0 <= minute <= 59):
        return None
    pm = meridiem.lower().startswith("p")
    hour = hour % 12 + (12 if pm else 0)
    return f"{hour:02d}:{minute:02d}"


def parse_time(text: str) -> TimeResult:
    I = re.I
    for m in re.finditer(r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)(?![a-z])", text, I):
        v = _to24(int(m[1]), int(m[2] or 0), m[3])
        if v:
            return TimeResult(v, m.span())

    for m in re.finditer(r"\b(\d{1,2})(?::(\d{2}))?\s*(?:o'clock\s*)?(?:in the|at)\s+(morning|afternoon|evening|night)\b", text, I):
        v = _to24(int(m[1]), int(m[2] or 0), "am" if m[3].lower() == "morning" else "pm")
        if v:
            return TimeResult(v, m.span())

    m = re.search(r"\b([01]?\d|2[0-3]):([0-5]\d)\b(?!\s*(?:a\.?m|p\.?m))", text, I)
    if m:
        return TimeResult(f"{int(m[1]):02d}:{m[2]}", m.span())

    m = re.search(r"\bnoon\b", text, I)
    if m:
        return TimeResult("12:00", m.span())
    m = re.search(r"\bmidnight\b", text, I)
    if m:
        return TimeResult("00:00", m.span())

    m = re.search(r"\bat\s+(\d{1,2})\b(?!\s*(?:st|nd|rd|th|\d|:|-|/|[a-z]))", text, I)
    if m and 1 <= int(m[1]) <= 12:
        h = int(m[1])
        meridiem = "pm" if (h <= 6 or h == 12) else "am"
        v = _to24(h, 0, meridiem)
        return TimeResult(v, m.span(), [f"No AM/PM given for 'at {h}': assumed {meridiem.upper()} ({v})."])
    return TimeResult()


_REMINDER_RE = re.compile(
    r"\b(\d+)\s*(minutes?|mins?|hours?|hrs?|days?|weeks?)\s*(?:before|prior|earlier|ahead|in advance|beforehand)\b", re.I)


def parse_reminders(text: str) -> Tuple[List[int], str]:
    """Return (offsets in minutes, text with reminder phrases blanked out)."""
    offsets: List[int] = []
    for m in _REMINDER_RE.finditer(text):
        unit = m[2].lower().rstrip("s")
        minutes = int(m[1]) * UNIT_MINUTES[unit]
        if minutes not in offsets:
            offsets.append(minutes)
    return offsets, _REMINDER_RE.sub(" ", text)
