"""Evaluation framework.

    python -m evaluation.evaluate                 # offline rule-based baseline
    python -m evaluation.evaluate --mode llm --prompt v2
    python -m evaluation.evaluate --compare       # rules vs LLM v1 vs LLM v2 (needs API key)

Nothing here is hard-coded: every number printed is measured on this run.
"""
import argparse
import csv
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

from config.settings import EVAL_NOW, settings
from database.database import Database
from database.repositories import DuplicateEventError
from evaluation.metrics import avg, pct, rate, title_match
from nlp.extractor import NLPExtractor
from services.calendar_service import CalendarService, ValidationFailed
from services.llm_service import AnthropicLLM, LLMOutputError, LLMUnavailable
from services.validation import to_start


def load_dataset(path: str) -> List[Dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _mins(s: str) -> List[int]:
    return [int(x) for x in s.split(";") if x.strip()]


def evaluate(extractor: NLPExtractor, rows: List[Dict[str, str]], now: datetime, use_llm: bool) -> Dict[str, Any]:
    intent_ok, date_ok, time_ok, rem_ok, cat_ok, title_ok, overall = [], [], [], [], [], [], []
    task_ok, created_ok, sched_ok, invalid_ok = [], [], [], []
    latencies, fallbacks, failures = [], 0, []

    for row in rows:
        t0 = time.perf_counter()
        res = extractor.extract(row["text"], now, use_llm=use_llm)
        latencies.append((time.perf_counter() - t0) * 1000)
        ev = res.event
        fallbacks += res.source == "rules-fallback"
        i_ok = ev.intent == row["intent"]
        intent_ok.append(i_ok)

        if row["intent"] == "create_event":
            d_ok = (ev.date or "") == row["date"]
            t_ok = (ev.time or "") == row["time"]
            r_ok = sorted(ev.reminders) == sorted(_mins(row["reminder_minutes"]))
            c_ok = ev.category == row["category"]
            ti_ok = title_match(ev.title, row["title"])
            date_ok.append(d_ok); time_ok.append(t_ok); rem_ok.append(r_ok)
            cat_ok.append(c_ok); title_ok.append(ti_ok)
            allok = i_ok and d_ok and t_ok and r_ok and c_ok
            overall.append(allok)
            if not allok:
                failures.append({"text": row["text"], "expected": {k: row[k] for k in ("date", "time", "reminder_minutes", "category")},
                                 "got": {"intent": ev.intent, "date": ev.date, "time": ev.time,
                                         "reminders": ev.reminders, "category": ev.category}})

        # ---- task automation on a fresh in-memory DB -----------------------
        svc = CalendarService(Database(":memory:"))
        expected_valid = row["expected_valid"] == "true"
        created, scheduled = None, None
        if ev.intent == "create_event":
            try:
                created = svc.create_event(ev, now, row["text"])
                scheduled = sorted(created.scheduled)
            except (ValidationFailed, DuplicateEventError):
                created = None
        if expected_valid:
            task_ok.append(created is not None)
            exp_start = datetime.strptime(f"{row['date']} {row['time']}", "%Y-%m-%d %H:%M")
            exp_sched = sorted(m for m in _mins(row["reminder_minutes"]) if exp_start - timedelta(minutes=m) >= now)
            ok = created is not None and svc.list_events()[0]["start_time"] == exp_start.strftime("%Y-%m-%d %H:%M")
            created_ok.append(ok)
            sched_ok.append(ok and scheduled == exp_sched)
        else:
            handled = created is None  # must be refused, not saved
            task_ok.append(handled)
            invalid_ok.append(handled)

    # ---- duplicate prevention ---------------------------------------------
    dup_flags = []
    for row in [r for r in rows if r["expected_valid"] == "true"][:20]:
        svc = CalendarService(Database(":memory:"))
        ev = extractor.extract(row["text"], now, use_llm=False).event
        try:
            svc.create_event(ev, now)
            svc.create_event(ev, now)
            dup_flags.append(False)
        except DuplicateEventError:
            dup_flags.append(True)
        except ValidationFailed:
            pass

    return {
        "n_rows": len(rows), "n_create_rows": len(date_ok),
        "nlp": {"intent_accuracy": rate(intent_ok), "date_accuracy": rate(date_ok),
                "time_accuracy": rate(time_ok), "reminder_accuracy": rate(rem_ok),
                "category_accuracy": rate(cat_ok), "title_match_rate": rate(title_ok),
                "overall_structured_accuracy": rate(overall)},
        "automation": {"task_success_rate": rate(task_ok), "correct_event_creation_rate": rate(created_ok),
                       "correct_reminder_scheduling_rate": rate(sched_ok),
                       "invalid_input_handling_rate": rate(invalid_ok),
                       "duplicate_prevention_rate": rate(dup_flags)},
        "performance": {"avg_latency_ms": avg(latencies), "max_latency_ms": max(latencies) if latencies else 0},
        "reliability": {"fallback_rate_invalid_or_failed_llm": fallbacks / len(rows)},
        "failures": failures[:25],
    }


# ---------------------------------------------------------------------------
# Reliability suite (uses stub LLMs - deterministic, no API needed)
# ---------------------------------------------------------------------------
class _StubLLM:
    available = True

    def __init__(self, reply=None, error=None):
        self.reply, self.error = reply, error

    def complete(self, system, user):
        if self.error:
            raise self.error
        return self.reply


def reliability_suite(now: datetime = EVAL_NOW) -> List[Dict[str, Any]]:
    out = []

    def check(name, fn):
        try:
            ok, detail = fn()
        except Exception as e:  # an unhandled exception IS a failure
            ok, detail = False, f"unhandled {type(e).__name__}: {e}"
        out.append({"test": name, "passed": bool(ok), "detail": detail})

    rules = NLPExtractor(None)
    svc = lambda: CalendarService(Database(":memory:"))

    check("valid input", lambda: ((r := rules.extract("Exam on 2026-11-02 at 9 AM", now)).event.date == "2026-11-02", r.source))
    check("invalid input (gibberish)", lambda: (rules.extract("asdf qwerty", now).event.intent == "unknown", ""))
    check("ambiguous time warns", lambda: (any("AM/PM" in w for w in rules.extract("Meeting tomorrow at 3", now).warnings), ""))
    check("missing date refused", lambda: ("date" in (e := rules.extract("Dentist at 2 PM", now).event).missing_fields, e.missing_fields))
    check("missing time refused", lambda: ("time" in (e := rules.extract("Meeting tomorrow", now).event).missing_fields, e.missing_fields))

    def past():
        ev = rules.extract("Exam on 2020-01-05 at 3 PM", now).event
        try:
            svc().create_event(ev, now); return False, "saved a past event"
        except ValidationFailed as e:
            return True, str(e)
    check("past date rejected", past)

    def dup():
        s = svc(); ev = rules.extract("Exam on 2026-11-02 at 9 AM", now).event
        s.create_event(ev, now)
        try:
            s.create_event(ev, now); return False, "duplicate saved"
        except DuplicateEventError as e:
            return True, str(e)
    check("duplicate event rejected", dup)

    check("malformed LLM JSON -> fallback", lambda: ((r := NLPExtractor(_StubLLM("not json at all")).extract("Exam on 2026-11-02 at 9 AM", now)).source == "rules-fallback", r.warnings))
    check("API failure -> fallback", lambda: ((r := NLPExtractor(_StubLLM(error=LLMUnavailable("down"))).extract("Exam on 2026-11-02 at 9 AM", now)).source == "rules-fallback", r.warnings))
    check("impossible LLM date -> fallback", lambda: ((r := NLPExtractor(_StubLLM('{"intent":"create_event","title":"X","date":"2026-02-30","time":"10:00"}')).extract("Exam on 2026-11-02 at 9 AM", now)).source == "rules-fallback", ""))
    check("hallucinated location removed", lambda: (NLPExtractor(_StubLLM('{"intent":"create_event","title":"Meeting","date":"2026-10-07","time":"15:00","location":"Room 5","category":"Meeting","priority":"Medium","reminders":[]}')).extract("Meeting tomorrow at 3 PM", now).event.location == "", ""))
    check("hallucinated reminders removed", lambda: (NLPExtractor(_StubLLM('{"intent":"create_event","title":"Meeting","date":"2026-10-07","time":"15:00","reminders":[{"minutes_before":60}]}')).extract("Meeting tomorrow at 3 PM", now).event.reminders == [], ""))
    check("LLM date contradicting parser is overridden", lambda: (NLPExtractor(_StubLLM('{"intent":"create_event","title":"Meeting","date":"2026-12-25","time":"15:00"}')).extract("Meeting tomorrow at 3 PM", now).event.date == "2026-10-07", ""))
    return out


def run(mode: str, prompt: str, dataset: str, save: bool = True) -> Dict[str, Any]:
    llm = None
    if mode == "llm":
        llm = AnthropicLLM()
        if not llm.available:
            raise SystemExit("LLM mode needs ANTHROPIC_API_KEY in .env")
    extractor = NLPExtractor(llm, prompt)
    res = evaluate(extractor, load_dataset(dataset), EVAL_NOW, use_llm=(mode == "llm"))
    res["config"] = {"mode": mode, "prompt_version": prompt if mode == "llm" else None,
                     "model": settings.anthropic_model if mode == "llm" else "rule-based",
                     "temperature": settings.llm_temperature if mode == "llm" else None,
                     "reference_now": EVAL_NOW.isoformat(), "dataset": Path(dataset).name,
                     "run_at": datetime.now().isoformat(timespec="seconds")}
    res["reliability_suite"] = reliability_suite()
    if save:
        Path(settings.results_dir).mkdir(parents=True, exist_ok=True)
        name = f"results_{mode}" + (f"_{prompt}" if mode == "llm" else "") + ".json"
        (Path(settings.results_dir) / name).write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
    return res


def print_report(res: Dict[str, Any]) -> None:
    c = res["config"]
    print(f"\n=== {c['mode']} | prompt={c['prompt_version']} | model={c['model']} | rows={res['n_rows']} ===")
    for section in ("nlp", "automation"):
        for k, v in res[section].items():
            print(f"  {section:10s} {k:34s} {pct(v)}")
    print(f"  performance avg latency: {res['performance']['avg_latency_ms']:.1f} ms")
    print(f"  reliability fallback rate: {pct(res['reliability']['fallback_rate_invalid_or_failed_llm'])}")
    suite = res["reliability_suite"]
    print(f"  reliability suite: {sum(t['passed'] for t in suite)}/{len(suite)} passed")
    for t in suite:
        if not t["passed"]:
            print("    FAILED:", t["test"], t["detail"])
    if res["failures"]:
        print(f"  first failures ({len(res['failures'])} shown):")
        for f in res["failures"][:5]:
            print("   -", f["text"], "\n     expected", f["expected"], "\n     got     ", f["got"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["rules", "llm"], default="rules")
    ap.add_argument("--prompt", choices=["v1", "v2"], default="v2")
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--dataset", default=settings.dataset_path)
    a = ap.parse_args()
    if a.compare:
        runs = [("rules", "v2")]
        if AnthropicLLM().available:
            runs += [("llm", "v1"), ("llm", "v2")]
        else:
            print("No API key: comparing only the rule-based baseline. Add a key to compare prompts v1 vs v2.")
        results = [run(m, p, a.dataset) for m, p in runs]
        for r in results:
            print_report(r)
        print("\n| System | Overall | Date | Time | Reminders | Task success | Fallback | Avg ms |\n|---|---|---|---|---|---|---|---|")
        for r in results:
            c, n, au = r["config"], r["nlp"], r["automation"]
            label = c["mode"] + (f"-{c['prompt_version']}" if c["prompt_version"] else "")
            print(f"| {label} | {pct(n['overall_structured_accuracy'])} | {pct(n['date_accuracy'])} | {pct(n['time_accuracy'])} |"
                  f" {pct(n['reminder_accuracy'])} | {pct(au['task_success_rate'])} |"
                  f" {pct(r['reliability']['fallback_rate_invalid_or_failed_llm'])} | {r['performance']['avg_latency_ms']:.0f} |")
    else:
        print_report(run(a.mode, a.prompt, a.dataset))


if __name__ == "__main__":
    main()
