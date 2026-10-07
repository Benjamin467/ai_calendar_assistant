"""Small hand-built lexicons used for feature engineering and rule-based fallback."""

# Order matters: the first matching category wins.
CATEGORY_KEYWORDS = [
    ("Interview", ["interview"]),
    ("Exam", ["exam", "midterm", "quiz", "test"]),
    ("Birthday", ["birthday", "anniversary"]),
    ("Presentation", ["presentation", "defense", "defence", "demo"]),
    ("Appointment", ["appointment", "dentist", "doctor", "clinic", "haircut", "checkup", "check-up"]),
    ("Meeting", ["meeting", "call", "standup", "sync", "catch up", "catch-up"]),
    ("Deadline", ["deadline", "due", "submit", "submission"]),
    ("Class", ["class", "lecture", "tutorial", "lesson"]),
    ("Sport", ["sport", "sports", "football", "soccer", "basketball", "gym", "workout", "training", "exercise"]),
    ("Travel", ["flight", "train", "trip", "bus"]),
    ("Social", ["party", "dinner", "lunch", "concert", "wedding"]),
]

URGENCY_WORDS = ["urgent", "important", "asap", "critical", "don't forget", "must"]
HIGH_PRIORITY_CATEGORIES = {"Exam", "Interview", "Appointment", "Deadline", "Presentation"}
LOW_PRIORITY_CATEGORIES = {"Social"}

DELETE_WORDS = ["delete", "cancel", "remove"]
EDIT_WORDS = ["reschedule", "postpone", "move", "change", "update"]
VIEW_PATTERNS = [r"\bshow\b", r"\blist\b", r"\bdisplay\b", r"\bdo i have\b", r"\bwhat(?:'s| is) on\b"]
CREATE_CUES = ["remind", "schedule", "alarm", "alert", "notify", "set up", "book", "add", "i have", "i've got"]
