"""Hybrid NLP pipeline: LLM structured extraction + deterministic cross-checks.

    text -> preprocess -> features -> LLM (JSON) -> schema validation
         -> reconcile with rule-based parser -> EventExtraction

If the LLM fails for ANY reason the rule-based extractor is used instead.
"""
from __future__ import annotations

import json
import logging
import re
import time as _time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from config.settings import settings
from models.schemas import EventExtraction, SchemaError
from nlp.features import extract_features
from nlp.preprocessing import normalize
from nlp.prompts import build_system_prompt
from nlp.rules import RuleBasedExtractor
from services.llm_service import LLMError, LLMOutputError

log = logging.getLogger(__name__)
_REMINDER_CUES = re.compile(r"\b(remind|alert|notify|before|notification|alarm|prior|ahead)\b", re.I)


@dataclass
class ExtractionResult:
    event: EventExtraction
    source: str                       # "llm", "rules", "rules-fallback"
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    features: Dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float = 0.0
    raw_llm: Optional[str] = None


def parse_llm_json(raw: str) -> EventExtraction:
    """Tolerate code fences / chatter around the JSON, but nothing else."""
    s = raw.strip()
    a, b = s.find("{"), s.rfind("}")
    if a == -1 or b <= a:
        raise LLMOutputError("No JSON object found in model output.")
    try:
        data = json.loads(s[a:b + 1])
    except json.JSONDecodeError as e:
        raise LLMOutputError(f"Malformed JSON from model: {e.msg}") from e
    try:
        return EventExtraction.from_dict(data)
    except SchemaError as e:
        raise LLMOutputError(f"Schema violation: {e}") from e


class NLPExtractor:
    def __init__(self, llm=None, prompt_version: Optional[str] = None):
        self.llm = llm
        self.prompt_version = prompt_version or settings.prompt_version
        self.rules = RuleBasedExtractor()

    def extract(self, text: str, now: Optional[datetime] = None, use_llm: bool = True) -> ExtractionResult:
        t0 = _time.perf_counter()
        now = now or datetime.now()
        clean = normalize(text)
        if not clean:
            return ExtractionResult(EventExtraction(intent="unknown"), "rules",
                                    errors=["Please type a request first."])
        if len(clean) > settings.max_input_chars:
            return ExtractionResult(EventExtraction(intent="unknown"), "rules",
                                    errors=[f"Input is too long (max {settings.max_input_chars} characters)."])

        features = extract_features(clean, now)
        rule_event, warnings = self.rules.extract(clean, now)
        result = ExtractionResult(rule_event, "rules", warnings, [], features)

        if use_llm and self.llm is not None and getattr(self.llm, "available", True):
            try:
                raw = self.llm.complete(build_system_prompt(self.prompt_version, now), clean)
                result.raw_llm = raw
                llm_event = parse_llm_json(raw)
                result.event = self._reconcile(llm_event, rule_event, clean, result.warnings)
                result.source = "llm"
            except LLMError as e:
                log.warning("LLM failed (%s); using rule-based fallback", e)
                result.source = "rules-fallback"
                result.warnings.append(f"AI unavailable or invalid output ({e}). Used offline rules instead.")
        result.event.compute_missing()
        result.elapsed_ms = (_time.perf_counter() - t0) * 1000
        return result

    @staticmethod
    def _reconcile(llm: EventExtraction, rules: EventExtraction, text: str, warns: List[str]) -> EventExtraction:
        """Hallucination guards: deterministic facts override the LLM."""
        ev = llm
        low = text.lower()
        if ev.location and ev.location.lower() not in low:
            warns.append(f"Removed location '{ev.location}' because it is not in your text.")
            ev.location = ""
        if ev.description and not all(w in low for w in re.findall(r"[a-z0-9']+", ev.description.lower())):
            ev.description = ""
        for fld in ("date", "time"):
            r, l = getattr(rules, fld), getattr(ev, fld)
            if r and l != r:
                if l:
                    warns.append(f"AI proposed {fld} {l}; the rule-based parser found {r}. Using {r}.")
                setattr(ev, fld, r)
            elif not r and l:
                warns.append(f"The {fld} {l} came only from the AI - please verify it.")
        if rules.reminders:
            ev.reminders = list(rules.reminders)
        elif ev.reminders and not _REMINDER_CUES.search(text):
            warns.append("Removed AI-invented reminders (none requested).")
            ev.reminders = []
        if rules.intent in ("delete_event", "edit_event", "view_events") and ev.intent == "create_event":
            ev.intent = rules.intent
        return ev
