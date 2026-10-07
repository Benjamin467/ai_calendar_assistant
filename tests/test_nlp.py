from datetime import date, datetime
from nlp.extractor import NLPExtractor, parse_llm_json
from nlp.temporal_parser import parse_date, parse_reminders, parse_time
from nlp.preprocessing import preprocess
from services.llm_service import LLMOutputError, LLMUnavailable
import pytest

NOW = datetime(2026, 10, 6, 9, 0)
X = NLPExtractor(None)


def ex(t):
    return X.extract(t, NOW).event


def test_preprocess_number_words():
    assert preprocess("one day  before") == "1 day before"


def test_date_relative():
    assert parse_date("tomorrow", date(2026, 10, 6)).value == date(2026, 10, 7)
    assert parse_date("next Friday", date(2026, 10, 6)).value == date(2026, 10, 9)
    assert parse_date("in 2 weeks", date(2026, 10, 6)).value == date(2026, 10, 20)


def test_date_absolute_and_year_rollover():
    assert parse_date("on October 15", date(2026, 10, 6)).value == date(2026, 10, 15)
    assert parse_date("on January 5", date(2026, 10, 6)).value == date(2027, 1, 5)
    assert parse_date("25/12/2026", date(2026, 10, 6)).value == date(2026, 12, 25)


def test_date_invalid():
    r = parse_date("February 30", date(2026, 10, 6))
    assert r.value is None and r.error


def test_time_formats():
    assert parse_time("at 3 PM").value == "15:00"
    assert parse_time("9:30 am").value == "09:30"
    assert parse_time("at 14:00").value == "14:00"
    assert parse_time("at 8 in the morning").value == "08:00"
    assert parse_time("at noon").value == "12:00"


def test_time_ambiguous_has_warning():
    r = parse_time("at 3")
    assert r.value == "15:00" and r.warnings


def test_reminders():
    offsets, _ = parse_reminders(preprocess("Alert me one day before and one hour before"))
    assert offsets == [1440, 60]
    assert parse_reminders("24 hours before")[0] == [1440]


def test_full_extraction_brief_examples():
    e = ex("I have a dentist appointment on October 15 at 2 PM. Remind me two days before and one hour before.")
    assert (e.title, e.date, e.time, e.reminders, e.category) == ("Dentist Appointment", "2026-10-15", "14:00", [2880, 60], "Appointment")
    e = ex("Set an alarm for my interview on Friday at 8 in the morning.")
    assert (e.title, e.date, e.time) == ("Interview", "2026-10-09", "08:00")


def test_no_invented_location():
    assert ex("Meeting tomorrow at 3 PM").location == ""


def test_unknown_intent():
    assert ex("asdf qwerty").intent == "unknown"


def test_parse_llm_json_accepts_fenced_json():
    ev = parse_llm_json('```json\n{"intent":"create_event","title":"A","date":"2026-10-07","time":"15:00"}\n```')
    assert ev.date == "2026-10-07"


@pytest.mark.parametrize("bad", ["", "no json", '{"intent": "hack_system"}', '{"date": "2026-02-30"}', '{"time": "25:99"}', "[1,2]"])
def test_parse_llm_json_rejects_bad(bad):
    with pytest.raises(LLMOutputError):
        parse_llm_json(bad)
