"""Builds data/evaluation_dataset.csv - a SYNTHETIC, template-based evaluation set.

Why synthetic: there is no public dataset of calendar commands with
ground-truth structured labels, and calendar text is private. Labels are
assigned BY CONSTRUCTION from the template (not by running our parser), so the
evaluation is not circular. Reference "now" = Tuesday 2026-10-06 06:00.
Conventions: "next <weekday>" = first such weekday strictly after the reference date.
Run:  python -m evaluation.generate_dataset
"""
import csv
import random
from datetime import timedelta
from pathlib import Path

from config.settings import EVAL_NOW, settings

REF = EVAL_NOW.date()
D = lambda n: (REF + timedelta(days=n)).isoformat()

EVENTS = [  # phrase, expected title, category
    ("dentist appointment", "Dentist Appointment", "Appointment"),
    ("project presentation", "Project Presentation", "Presentation"),
    ("math exam", "Math Exam", "Exam"),
    ("meeting with John", "Meeting with John", "Meeting"),
    ("job interview", "Job Interview", "Interview"),
    ("doctor's appointment", "Doctor's Appointment", "Appointment"),
    ("AI assignment deadline", "AI Assignment Deadline", "Deadline"),
    ("team call", "Team Call", "Meeting"),
    ("physics quiz", "Physics Quiz", "Exam"),
    ("final year defense", "Final Year Defense", "Presentation"),
]
DATES = [  # phrase, expected ISO date
    ("tomorrow", D(1)), ("today", D(0)), ("day after tomorrow", D(2)),
    ("next Friday", D(3)), ("next Monday", D(6)), ("on Wednesday", D(1)),
    ("on October 15", "2026-10-15"), ("on 20 November", "2026-11-20"),
    ("on December 3rd", "2026-12-03"), ("in 3 days", D(3)), ("in 2 weeks", D(14)),
    ("on 2026-11-02", "2026-11-02"), ("on 25/12/2026", "2026-12-25"),
]
TIMES = [
    ("at 3 PM", "15:00"), ("at 9:30 AM", "09:30"), ("at 14:00", "14:00"),
    ("at 8 in the morning", "08:00"), ("at noon", "12:00"), ("at 7 PM", "19:00"),
    ("at 10am", "10:00"), ("at 6:45 pm", "18:45"), ("at 5 in the evening", "17:00"),
]
REMINDERS = [
    ("", []), ("", []),
    ("Remind me 30 minutes before.", [30]),
    ("Alert me one day before and one hour before.", [1440, 60]),
    ("Notify me 24 hours before.", [1440]),
    ("Remind me two days before.", [2880]),
    ("Alert me 15 minutes before.", [15]),
]
PREFIXES = ["Remind me about my {t}", "Schedule my {t}", "I have {a} {t}", "Set an alarm for my {t}", "Add my {t}", "Book my {t}"]


def article(t):
    return "an" if t[0].lower() in "aeiou" else "a"


def build_rows():
    rng = random.Random(42)
    rows = []
    for _ in range(115):
        ev, dt, tm, rem = rng.choice(EVENTS), rng.choice(DATES), rng.choice(TIMES), rng.choice(REMINDERS)
        pre = rng.choice(PREFIXES).format(t=ev[0], a=article(ev[0]))
        when = f"{dt[0]} {tm[0]}" if rng.random() < 0.5 else f"{tm[0]} {dt[0]}"
        text = f"{pre} {when}." + (f" {rem[0]}" if rem[0] else "")
        rows.append(dict(text=text, intent="create_event", title=ev[1], date=dt[1], time=tm[1],
                         reminder_minutes=";".join(map(str, rem[1])), category=ev[2],
                         expected_valid="true", note="template"))
    hand = [  # natural phrasing taken from the assignment brief + edge cases
        ("Meeting with John tomorrow at 3.", "create_event", "Meeting with John", D(1), "15:00", "", "Meeting", "true", "ambiguous time (no am/pm)"),
        ("Remind me about Sarah's birthday on December 20.", "create_event", "Sarah's Birthday", "2026-12-20", "", "", "Birthday", "false", "missing time"),
        ("Set an alarm for my interview on Friday at 8 in the morning.", "create_event", "Interview", D(3), "08:00", "", "Interview", "true", "brief example"),
        ("I have a doctor's appointment next Wednesday at 4 PM. Notify me 24 hours before.", "create_event", "Doctor's Appointment", D(1), "16:00", "1440", "Appointment", "true", "brief example"),
        ("Schedule my AI assignment presentation for next Monday at 9:30 AM.", "create_event", "AI Assignment Presentation", D(6), "09:30", "", "Presentation", "true", "brief example"),
        ("I have a dentist appointment on October 15 at 2 PM. Remind me two days before and one hour before.", "create_event", "Dentist Appointment", "2026-10-15", "14:00", "2880;60", "Appointment", "true", "brief example"),
        ("My AI project presentation is today at 3:00 PM. Remind me 5 minutes before.", "create_event", "AI Project Presentation", D(0), "15:00", "5", "Presentation", "true", "demo scenario"),
        ("Dentist appointment at 2 PM", "create_event", "Dentist Appointment", "", "14:00", "", "Appointment", "false", "missing date"),
        ("Team meeting tomorrow", "create_event", "Team Meeting", D(1), "", "", "Meeting", "false", "missing time"),
        ("Remind me to call mom tomorrow at 5 PM", "create_event", "Call Mom", D(1), "17:00", "", "Meeting", "true", "task phrasing"),
        ("Lunch with Sarah on 20 November at noon", "create_event", "Lunch with Sarah", "2026-11-20", "12:00", "", "Social", "true", "social"),
        ("Exam on 2020-01-05 at 3 PM", "create_event", "Exam", "2020-01-05", "15:00", "", "Exam", "false", "past date"),
        ("Meeting on February 30 at 3 PM", "create_event", "Meeting", "", "15:00", "", "Meeting", "false", "invalid date"),
        ("Interview on 2026-13-40 at 9 AM", "create_event", "Interview", "", "09:00", "", "Interview", "false", "invalid date"),
        ("Meeting today at 5 AM", "create_event", "Meeting", D(0), "05:00", "", "Meeting", "false", "earlier today (past)"),
        ("asdf qwerty", "unknown", "", "", "", "", "", "false", "gibberish"),
        ("What is the weather like", "unknown", "", "", "", "", "", "false", "off-topic"),
        ("hello there", "unknown", "", "", "", "", "", "false", "off-topic"),
        ("Delete my dentist appointment", "delete_event", "", "", "", "", "", "false", "other intent"),
        ("Reschedule my exam to Friday", "edit_event", "", "", "", "", "", "false", "other intent"),
        ("Show my events for tomorrow", "view_events", "", "", "", "", "", "false", "other intent"),
    ]
    for h in hand:
        rows.append(dict(zip(["text", "intent", "title", "date", "time", "reminder_minutes",
                              "category", "expected_valid", "note"], h)))
    return rows


def main():
    rows = build_rows()
    path = Path(settings.dataset_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} rows to {path}")


if __name__ == "__main__":
    main()
