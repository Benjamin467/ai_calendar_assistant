from datetime import datetime
from models.schemas import EventExtraction

NOW = datetime(2026, 10, 6, 9, 0)


def make(cal, **kw):
    base = dict(intent="create_event", title="AI Project Presentation", date="2026-10-06", time="15:00", reminders=[60, 5])
    base.update(kw)
    return cal.create_event(EventExtraction(**base), NOW)


def test_past_reminders_skipped(cal):
    c = make(cal, date="2026-10-06", time="09:30", reminders=[60, 5])
    assert c.scheduled == [5] and c.skipped == [60]


def test_not_triggered_early(cal, rem):
    make(cal)
    assert rem.check_due(datetime(2026, 10, 6, 13, 0)) == []


def test_trigger_message_and_no_duplicates(cal, rem):
    make(cal)
    fired = rem.check_due(datetime(2026, 10, 6, 14, 0))
    assert fired == ["Reminder: AI Project Presentation starts in 1 hour."]
    assert rem.check_due(datetime(2026, 10, 6, 14, 1)) == []          # not sent twice
    assert len(rem.notifier.history()) == 1


def test_second_reminder_fires_later(cal, rem):
    make(cal)
    rem.check_due(datetime(2026, 10, 6, 14, 0))
    assert rem.check_due(datetime(2026, 10, 6, 14, 55)) == ["Reminder: AI Project Presentation starts in 5 minutes."]


def test_late_reminder_marked_late(cal, rem):
    make(cal)
    fired = rem.check_due(datetime(2026, 10, 6, 16, 0))
    assert all("late" in m for m in fired) and len(fired) == 2


def test_dismiss_and_complete(cal, rem):
    make(cal)
    pending = rem.list("pending")
    assert rem.dismiss(pending[0]["id"])
    rem.check_due(datetime(2026, 10, 6, 14, 55))
    triggered = rem.list("triggered")
    assert len(triggered) == 1 and rem.complete(triggered[0]["id"])
    assert not rem.complete(pending[0]["id"])                           # dismissed cannot be completed


def test_dismissed_reminder_never_fires(cal, rem):
    make(cal, reminders=[60])
    rem.dismiss(rem.list("pending")[0]["id"])
    assert rem.check_due(datetime(2026, 10, 6, 14, 30)) == []


def test_unseen_notifications_flow(cal, rem):
    make(cal)
    rem.check_due(datetime(2026, 10, 6, 14, 0))
    n = rem.notifier.unseen()
    assert len(n) == 1
    rem.notifier.mark_seen([n[0]["id"]])
    assert rem.notifier.unseen() == []
