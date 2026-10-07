"""Auxiliary NLP feature engineering (shown in the evaluation / UI)."""
import re
from datetime import datetime
from typing import Any, Dict

from nlp import lexicon
from nlp.preprocessing import preprocess
from nlp.rules import detect_category, detect_intent_hint
from nlp.temporal_parser import parse_date, parse_reminders, parse_time


def extract_features(text: str, now: datetime) -> Dict[str, Any]:
    t = preprocess(text)
    offsets, rest = parse_reminders(t)
    d = parse_date(rest, now.date())
    tm = parse_time(rest)
    cat, kw = detect_category(rest)
    caps = re.findall(r"(?<!^)(?<![.!?]\s)\b[A-Z][a-z]+\b", t)
    return {
        "n_tokens": len(t.split()),
        "intent_indicator": detect_intent_hint(t),
        "has_date_expression": bool(d.value or d.error),
        "date_expression_type": d.kind,
        "is_relative_date": d.relative,
        "has_time_expression": bool(tm.value),
        "time_is_ambiguous": bool(tm.warnings),
        "n_reminder_expressions": len(offsets),
        "category_keyword": kw or None,
        "urgency_indicator": any(w in t.lower() for w in lexicon.URGENCY_WORDS),
        "named_entity_candidates": caps,
    }
