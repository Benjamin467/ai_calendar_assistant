"""Offline rule-based extractor: regex temporal parser + keyword lexicons.

Serves three roles: (1) fallback when the LLM is unavailable or returns bad
output, (2) deterministic cross-check of the LLM's dates/times/reminders,
(3) baseline for the evaluation.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import List, Tuple

from models.schemas import EventExtraction
from nlp import lexicon
from nlp.preprocessing import preprocess
from nlp.temporal_parser import MONTHS, WEEKDAYS, parse_date, parse_reminders, parse_time

_REMIND_CLAUSE = re.compile(r"\b(?:and\s+)?(?:please\s+)?(?:alert|notify|remind)\s+me\b\s*(?:about|of|to|that)?", re.I)
_PREFIX = re.compile(
    r"^\s*(?:please\s+)?(?:i\s+(?:have|got|need\s+to|am\s+having)|i've\s+got|schedule|"
    r"set\s+(?:an?\s+)?(?:alarm|reminder)\s+for|set\s+up|create|add|book|put)\b\s*(?:an?\s+)?", re.I)
_LOCATION = re.compile(r"\b(?:at|in)\s+(?:the\s+)?([A-Z][\w'-]*(?:\s+[A-Z0-9][\w'-]*)*)")
_DURATION = re.compile(r"\bfor\s+(\d+)\s*(hours?|hrs?|minutes?|mins?)\b|\b(\d+)-(hour|minute)\b", re.I)
_LEAD = {"my", "the", "a", "an", "to", "about", "for", "of", "our", "your", "that"}
_TRAIL = {"is", "are", "starts", "start", "begins", "on", "at", "in", "for", "and", "the", "by", "from", "will", "be", "of"}
_SMALL = {"with", "of", "for", "and", "the", "to", "at", "in", "on", "a", "an"}
_NOT_PLACES = set(MONTHS) | set(WEEKDAYS) | {"morning", "afternoon", "evening", "night"}


def title_case(t: str) -> str:
    out = []
    for i, w in enumerate(t.split()):
        if w.isupper() or (i > 0 and w.lower() in _SMALL):
            out.append(w if w.isupper() else w.lower())
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out)


def _remove_spans(text: str, spans: List[Tuple[int, int]]) -> str:
    for a, b in sorted([s for s in spans if s], reverse=True):
        text = text[:a] + " " + text[b:]
    return text


def _clean_title(t: str) -> str:
    t = _REMIND_CLAUSE.sub(" ", t)
    t = re.sub(r"[.,!?;:]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = _PREFIX.sub("", t)
    words = t.split()
    while words and words[0].lower() in _LEAD:
        words.pop(0)
    while words and words[-1].lower() in _TRAIL:
        words.pop()
    return title_case(" ".join(words))


def detect_category(text: str) -> Tuple[str, str]:
    low = text.lower()
    for cat, kws in lexicon.CATEGORY_KEYWORDS:
        for kw in kws:
            if re.search(rf"\b{re.escape(kw)}(?:s|es)?\b", low):
                return cat, kw
    return "General", ""


def detect_intent_hint(text: str) -> str:
    low = text.lower()
    if any(re.search(rf"\b{w}\b", low) for w in lexicon.DELETE_WORDS):
        return "delete_event"
    if any(re.search(rf"\b{w}\b", low) for w in lexicon.EDIT_WORDS):
        return "edit_event"
    if any(re.search(p, low) for p in lexicon.VIEW_PATTERNS):
        return "view_events"
    return "create_event"


class RuleBasedExtractor:
    def extract(self, raw_text: str, now: datetime) -> Tuple[EventExtraction, List[str]]:
        text = preprocess(raw_text)
        warnings: List[str] = []
        intent = detect_intent_hint(text)

        offsets, t1 = parse_reminders(text)
        date_r = parse_date(t1, now.date())
        time_r = parse_time(t1)
        loc_m = None
        for m in _LOCATION.finditer(t1):
            first = m.group(1).split()[0].lower()
            if first not in _NOT_PLACES:
                loc_m = m
                break
        dur_m = _DURATION.search(t1)

        spans = [date_r.span, time_r.span, dur_m.span() if dur_m else None]
        location = ""
        if loc_m:
            location = loc_m.group(1).strip()
            spans.append((loc_m.start(1), loc_m.end(1)))
        title = _clean_title(_remove_spans(t1, spans))

        duration = 60
        if dur_m:
            n = int(dur_m.group(1) or dur_m.group(3))
            unit = (dur_m.group(2) or dur_m.group(4)).lower()
            duration = n * 60 if unit.startswith(("h",)) else n
            duration = min(max(duration, 1), 1440)

        category, _ = detect_category(title or t1)
        has_cue = any(re.search(rf"\b{re.escape(c)}", text.lower()) for c in lexicon.CREATE_CUES)
        has_when = bool(date_r.value or date_r.error or time_r.value or offsets)
        if intent == "create_event" and not (title and (has_when or has_cue or category != "General")):
            return EventExtraction(intent="unknown").compute_missing(), ["Could not recognise a calendar request."]

        priority = "Medium"
        if category in lexicon.HIGH_PRIORITY_CATEGORIES or any(w in text.lower() for w in lexicon.URGENCY_WORDS):
            priority = "High"
        elif category in lexicon.LOW_PRIORITY_CATEGORIES:
            priority = "Low"

        if date_r.error:
            warnings.append(date_r.error)
        warnings += date_r.warnings + time_r.warnings

        ev = EventExtraction(
            intent=intent, title=title, description="",
            date=date_r.value.isoformat() if date_r.value else None,
            time=time_r.value, duration_minutes=duration, location=location,
            category=category, priority=priority, reminders=offsets,
        ).compute_missing()
        return ev, warnings
