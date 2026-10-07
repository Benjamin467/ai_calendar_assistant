"""Controlled task-automation layer. Only these predefined actions exist."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from database.database import Database
from database.repositories import (DuplicateEventError, EventRepository, LogRepository,
                                   ReminderRepository, fmt)
from models.schemas import CATEGORIES, PRIORITIES, EventExtraction
from services.validation import to_start, validate_for_scheduling

__all__ = ["CalendarService", "CreatedEvent", "ValidationFailed", "DuplicateEventError"]


class ValidationFailed(Exception):
    def __init__(self, errors: List[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass
class CreatedEvent:
    event_id: int
    scheduled: List[int] = field(default_factory=list)
    skipped: List[int] = field(default_factory=list)


class CalendarService:
    def __init__(self, db: Database):
        self.events = EventRepository(db)
        self.reminders = ReminderRepository(db)
        self.log = LogRepository(db)

    def create_event(self, ev: EventExtraction, now: Optional[datetime] = None,
                     source_text: str = "") -> CreatedEvent:
        now = now or datetime.now()
        errors, _ = validate_for_scheduling(ev, now)
        if errors:
            self.log.add("create_rejected", "; ".join(errors), now)
            raise ValidationFailed(errors)
        start = to_start(ev)
        event_id = self.events.add({
            "title": ev.title, "description": ev.description, "start_time": fmt(start),
            "duration_minutes": ev.duration_minutes, "location": ev.location,
            "category": ev.category, "priority": ev.priority, "source_text": source_text[:500],
        }, now)
        created = CreatedEvent(event_id)
        for m in ev.reminders:
            trigger = start - timedelta(minutes=m)
            if trigger < now:
                created.skipped.append(m)
                continue
            if self.reminders.add(event_id, m, trigger) is not None:
                created.scheduled.append(m)
        self.log.add("event_created", f"#{event_id} {ev.title} @ {fmt(start)} reminders={created.scheduled}", now)
        return created

    def list_events(self, search: str = "") -> List[Dict[str, Any]]:
        return self.events.list(search)

    def get_event(self, event_id: int):
        return self.events.get(event_id)

    def update_event(self, event_id: int, fields: Dict[str, Any], now: Optional[datetime] = None) -> None:
        now = now or datetime.now()
        current = self.events.get(event_id)
        if not current:
            raise ValidationFailed(["Event not found."])
        errors: List[str] = []
        title = str(fields.get("title", current["title"])).strip()
        if not title:
            errors.append("The event needs a title.")
        start_s = fields.get("start_time", current["start_time"])
        try:
            start = datetime.strptime(start_s, "%Y-%m-%d %H:%M")
        except ValueError:
            start = None
            errors.append("Invalid date/time.")
        if start and start < now and start_s != current["start_time"]:
            errors.append("The new time is in the past.")
        if fields.get("category", current["category"]) not in CATEGORIES:
            errors.append("Unknown category.")
        if fields.get("priority", current["priority"]) not in PRIORITIES:
            errors.append("Unknown priority.")
        if errors:
            raise ValidationFailed(errors)
        self.events.update(event_id, {**fields, "title": title})
        if start:
            self.reminders.retime(event_id, start)
        self.log.add("event_updated", f"#{event_id} {sorted(fields)}", now)

    def delete_event(self, event_id: int, now: Optional[datetime] = None) -> bool:
        now = now or datetime.now()
        ok = self.events.delete(event_id)
        if ok:
            self.log.add("event_deleted", f"#{event_id}", now)
        return ok

    def events_between(self, start: datetime, end: datetime):
        return self.events.between(fmt(start), fmt(end))
