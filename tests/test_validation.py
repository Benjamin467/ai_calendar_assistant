from datetime import datetime
import pytest
from models.schemas import EventExtraction, SchemaError
from services.validation import validate_for_scheduling

NOW = datetime(2026, 10, 6, 9, 0)


def ev(**kw):
    base = dict(intent="create_event", title="Exam", date="2026-11-02", time="09:00")
    base.update(kw)
    return EventExtraction(**base)


def test_valid_event_has_no_errors():
    assert validate_for_scheduling(ev(), NOW)[0] == []


def test_missing_fields_are_errors():
    errs, _ = validate_for_scheduling(ev(date=None, time=None), NOW)
    assert len(errs) == 2


def test_past_event_rejected():
    assert any("past" in e for e in validate_for_scheduling(ev(date="2020-01-01"), NOW)[0])


def test_far_future_rejected():
    assert validate_for_scheduling(ev(date="2040-01-01"), NOW)[0]


def test_past_reminder_is_warning_not_error():
    errs, warns = validate_for_scheduling(ev(date="2026-10-06", time="10:00", reminders=[1440]), NOW)
    assert not errs and warns


def test_non_create_intent_blocked():
    assert validate_for_scheduling(ev(intent="delete_event"), NOW)[0]


@pytest.mark.parametrize("data", [
    {"intent": "rm -rf"}, {"date": "15/10/2026"}, {"time": "7pm"}, {"duration_minutes": 99999},
    {"priority": "Urgent!!"}, {"reminders": [{"minutes_before": -5}]}, {"reminders": "soon"},
    {"title": 123}, "not a dict"])
def test_schema_rejects(data):
    with pytest.raises(SchemaError):
        EventExtraction.from_dict(data)


def test_schema_normalises():
    e = EventExtraction.from_dict({"title": "  A   B ", "time": "9:05", "category": "weird", "priority": "high",
                                   "reminders": [{"minutes_before": 60}, 60]})
    assert (e.title, e.time, e.category, e.priority, e.reminders) == ("A B", "09:05", "General", "High", [60])
