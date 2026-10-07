"""Validation layer: the gate between AI output and any calendar action."""
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from models.schemas import EventExtraction


def to_start(ev: EventExtraction) -> Optional[datetime]:
    if not (ev.date and ev.time):
        return None
    try:
        return datetime.strptime(f"{ev.date} {ev.time}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def validate_for_scheduling(ev: EventExtraction, now: datetime) -> Tuple[List[str], List[str]]:
    """Return (errors, warnings). Any error blocks saving."""
    errors: List[str] = []
    warnings: List[str] = []
    if ev.intent != "create_event":
        errors.append(f"Intent '{ev.intent}' cannot be saved as a new event.")
        return errors, warnings
    if not ev.title:
        errors.append("The event needs a title.")
    if not ev.date:
        errors.append("The event needs a date.")
    if not ev.time:
        errors.append("The event needs a time.")
    start = to_start(ev)
    if ev.date and ev.time and start is None:
        errors.append("The date or time is not valid.")
    if start:
        if start < now:
            errors.append(f"The event time ({start:%Y-%m-%d %H:%M}) is in the past.")
        elif start > now + timedelta(days=365 * 5):
            errors.append("The event is more than 5 years away - please check the date.")
        for m in ev.reminders:
            if start - timedelta(minutes=m) < now:
                warnings.append(f"Reminder {m} minutes before is already in the past and will be skipped.")
    return errors, warnings
