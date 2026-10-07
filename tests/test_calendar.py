from datetime import datetime
import pytest
from models.schemas import EventExtraction
from services.calendar_service import DuplicateEventError, ValidationFailed

NOW = datetime(2026, 10, 6, 9, 0)


def ev(**kw):
    base = dict(intent="create_event", title="Exam", date="2026-11-02", time="09:00", reminders=[1440, 60])
    base.update(kw)
    return EventExtraction(**base)


def test_create_and_retrieve(cal):
    c = cal.create_event(ev(), NOW, "text")
    row = cal.get_event(c.event_id)
    assert row["title"] == "Exam" and row["start_time"] == "2026-11-02 09:00"
    assert sorted(c.scheduled) == [60, 1440]


def test_invalid_event_not_saved(cal):
    with pytest.raises(ValidationFailed):
        cal.create_event(ev(date=None), NOW)
    assert cal.list_events() == []


def test_duplicate_prevention(cal):
    cal.create_event(ev(), NOW)
    with pytest.raises(DuplicateEventError):
        cal.create_event(ev(), NOW)
    assert len(cal.list_events()) == 1


def test_search(cal):
    cal.create_event(ev(title="Dentist"), NOW)
    cal.create_event(ev(title="Math exam", time="10:00"), NOW)
    assert [e["title"] for e in cal.list_events("dent")] == ["Dentist"]


def test_update_retimes_pending_reminders(cal):
    c = cal.create_event(ev(reminders=[60]), NOW)
    cal.update_event(c.event_id, {"start_time": "2026-11-03 12:00"}, NOW)
    assert cal.reminders.for_event(c.event_id)[0]["trigger_time"] == "2026-11-03 11:00"


def test_update_rejects_past(cal):
    c = cal.create_event(ev(), NOW)
    with pytest.raises(ValidationFailed):
        cal.update_event(c.event_id, {"start_time": "2020-01-01 10:00"}, NOW)


def test_delete_cascades_reminders(cal):
    c = cal.create_event(ev(), NOW)
    assert cal.delete_event(c.event_id, NOW)
    assert cal.get_event(c.event_id) is None
    assert cal.reminders.for_event(c.event_id) == []
    assert not cal.delete_event(c.event_id, NOW)
