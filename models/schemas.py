"""Structured schema + strict validation for everything the AI returns.

The LLM is never trusted: its JSON is converted to an EventExtraction through
`from_dict`, which rejects anything outside the allowed schema.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Any, Dict, List, Optional

INTENTS = ("create_event", "edit_event", "delete_event", "view_events", "unknown")
CATEGORIES = ("Meeting", "Appointment", "Exam", "Birthday", "Deadline",
              "Interview", "Presentation", "Class", "Social", "Sport", "Travel", "General")
PRIORITIES = ("Low", "Medium", "High")
MAX_REMINDER_MINUTES = 60 * 24 * 365


class SchemaError(ValueError):
    """Raised when structured data does not satisfy the schema."""


@dataclass
class EventExtraction:
    intent: str = "create_event"
    title: str = ""
    description: str = ""
    date: Optional[str] = None            # ISO "YYYY-MM-DD"
    time: Optional[str] = None            # 24h "HH:MM"
    duration_minutes: int = 60
    location: str = ""
    category: str = "General"
    priority: str = "Medium"
    reminders: List[int] = field(default_factory=list)  # minutes before start
    missing_fields: List[str] = field(default_factory=list)

    # ---- validation ---------------------------------------------------
    @classmethod
    def from_dict(cls, data: Any) -> "EventExtraction":
        if not isinstance(data, dict):
            raise SchemaError("AI output must be a JSON object.")

        intent = str(data.get("intent") or "create_event").strip().lower()
        if intent not in INTENTS:
            raise SchemaError(f"Unsupported intent: {intent!r}")

        title = _text(data.get("title"), "title", 120)
        description = _text(data.get("description"), "description", 500)
        location = _text(data.get("location"), "location", 120)

        d = data.get("date")
        if d in (None, ""):
            d = None
        else:
            if not isinstance(d, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d.strip()):
                raise SchemaError(f"Date must be YYYY-MM-DD, got {d!r}")
            try:
                d = date.fromisoformat(d.strip()).isoformat()
            except ValueError:
                raise SchemaError(f"Impossible calendar date: {d!r}")

        t = data.get("time")
        if t in (None, ""):
            t = None
        else:
            if not isinstance(t, str) or not re.fullmatch(r"\d{1,2}:\d{2}", t.strip()):
                raise SchemaError(f"Time must be HH:MM, got {t!r}")
            try:
                t = datetime.strptime(t.strip(), "%H:%M").strftime("%H:%M")
            except ValueError:
                raise SchemaError(f"Impossible time of day: {t!r}")

        dur = data.get("duration_minutes")
        if dur in (None, ""):
            dur = 60
        if isinstance(dur, bool) or not isinstance(dur, (int, float, str)):
            raise SchemaError("duration_minutes must be a number")
        try:
            dur = int(float(dur))
        except ValueError:
            raise SchemaError("duration_minutes must be a number")
        if not 1 <= dur <= 1440:
            raise SchemaError("duration_minutes must be between 1 and 1440")

        category = str(data.get("category") or "General").strip().title()
        if category not in CATEGORIES:
            category = "General"  # unknown categories degrade safely

        priority = str(data.get("priority") or "Medium").strip().title()
        if priority not in PRIORITIES:
            raise SchemaError(f"Invalid priority: {priority!r}")

        raw_rem = data.get("reminders") or []
        if not isinstance(raw_rem, list):
            raise SchemaError("reminders must be a list")
        reminders: List[int] = []
        for r in raw_rem:
            m = r.get("minutes_before") if isinstance(r, dict) else r
            if isinstance(m, bool) or not isinstance(m, (int, float)) or int(m) != m:
                raise SchemaError(f"Invalid reminder offset: {r!r}")
            m = int(m)
            if not 0 <= m <= MAX_REMINDER_MINUTES:
                raise SchemaError(f"Reminder offset out of range: {m}")
            if m not in reminders:
                reminders.append(m)

        return cls(intent, title, description, d, t, dur, location,
                   category, priority, reminders)

    def compute_missing(self) -> "EventExtraction":
        self.missing_fields = []
        if self.intent == "create_event":
            if not self.title:
                self.missing_fields.append("title")
            if not self.date:
                self.missing_fields.append("date")
            if not self.time:
                self.missing_fields.append("time")
        return self

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["reminders"] = [{"minutes_before": m} for m in self.reminders]
        return d


def _text(v: Any, name: str, limit: int) -> str:
    if v is None:
        return ""
    if not isinstance(v, str):
        raise SchemaError(f"{name} must be a string")
    v = re.sub(r"\s+", " ", v).strip()
    if len(v) > limit:
        raise SchemaError(f"{name} is too long")
    return v
