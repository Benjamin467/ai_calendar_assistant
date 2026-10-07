"""Streamlit UI: AI-Powered Intelligent Calendar Reminder and Event Alert System."""
import logging
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from config.settings import settings
from database.database import Database, DatabaseError
from models.schemas import CATEGORIES, PRIORITIES, EventExtraction
from nlp.extractor import NLPExtractor
from nlp.prompts import build_system_prompt
from services.calendar_service import CalendarService, DuplicateEventError, ValidationFailed
from services.llm_service import AnthropicLLM
from services.notification_service import NotificationService
from services.reminder_service import ReminderScheduler, ReminderService, humanize_minutes
from services.validation import to_start, validate_for_scheduling

logging.basicConfig(level=logging.INFO)
st.set_page_config(page_title="AI Calendar Assistant", page_icon="📅", layout="wide")


@st.cache_resource
def get_services():
    """Created once per server process; also starts the background reminder scheduler."""
    db = Database(settings.db_path)
    notifier = NotificationService(db)
    reminders = ReminderService(db, notifier)
    scheduler = ReminderScheduler(reminders, settings.scheduler_interval)
    scheduler.start()
    return {"db": db, "cal": CalendarService(db), "rem": reminders, "notifier": notifier,
            "nlp": NLPExtractor(AnthropicLLM(), settings.prompt_version)}


try:
    S = get_services()
except DatabaseError as e:
    st.error(f"Database problem: {e}")
    st.stop()
cal, rem, notifier, nlp = S["cal"], S["rem"], S["notifier"], S["nlp"]


# ---- global alert listener: polls every 5 s and pops a toast for new alerts ----
@st.fragment(run_every=5)
def alert_listener():
    new = notifier.unseen()
    for n in new:
        st.toast(n["message"], icon="⏰")
    if new:
        notifier.mark_seen([n["id"] for n in new])
        for n in new:
            st.warning(f"⏰ {n['message']}")


st.sidebar.title("📅 AI Calendar")
page = st.sidebar.radio("Go to", ["Dashboard", "Create Event", "Events", "Reminder Center",
                                  "AI Test / Evaluation", "About"])
use_llm = st.sidebar.toggle("Use Claude (AI)", value=settings.use_llm and settings.llm_configured,
                            disabled=not settings.llm_configured,
                            help="Needs ANTHROPIC_API_KEY in .env. Off = offline rule-based NLP.")
# if not settings.llm_configured:
#     st.sidebar.info("No API key found - running with the offline rule-based extractor.")
st.sidebar.caption(f"Now: {datetime.now():%Y-%m-%d %H:%M:%S}")
with st.sidebar:
    alert_listener()


def fmt_dt(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M").strftime("%a %d %b %Y, %H:%M")


def due_in(trigger: str) -> str:
    secs = int((datetime.strptime(trigger, "%Y-%m-%d %H:%M") - datetime.now()).total_seconds())
    if secs <= 0:
        return "due now"
    h, rest = divmod(secs, 3600)
    return f"{h}h {rest // 60}m" if h else f"{rest // 60}m {rest % 60}s"


# =============================== Dashboard ===============================
if page == "Dashboard":
    st.title("Dashboard")
    now = datetime.now()
    today = cal.events_between(now.replace(hour=0, minute=0), now.replace(hour=0, minute=0) + timedelta(days=1))
    upcoming = [e for e in cal.list_events() if e["start_time"] >= now.strftime("%Y-%m-%d %H:%M")][:10]
    pending = rem.list("pending")
    c1, c2, c3 = st.columns(3)
    c1.metric("Today's events", len(today))
    c2.metric("Upcoming events", len(upcoming))
    c3.metric("Pending reminders", len(pending))
    st.subheader("Today")
    st.dataframe(pd.DataFrame(today)[["title", "start_time", "category", "priority"]] if today else pd.DataFrame(), use_container_width=True)
    st.subheader("Upcoming")
    st.dataframe(pd.DataFrame(upcoming)[["title", "start_time", "category", "priority"]] if upcoming else pd.DataFrame(), use_container_width=True)
    st.subheader("Pending reminders (countdown)")
    if pending:
        st.dataframe(pd.DataFrame([{"event": r["title"], "reminder": f"{humanize_minutes(r['minutes_before'])} before",
                                    "fires at": r["trigger_time"], "due in": due_in(r["trigger_time"])} for r in pending]),
                     use_container_width=True)
        st.caption("Refresh the page (or switch tabs) to update the countdown.")
    else:
        st.info("No pending reminders.")
    st.subheader("Recent alerts")
    hist = notifier.history(10)
    st.dataframe(pd.DataFrame(hist)[["created_at", "message"]] if hist else pd.DataFrame(), use_container_width=True)

# ============================== Create Event ==============================
elif page == "Create Event":
    st.title("Create Event with Natural Language")
    demo_time = datetime.now() + timedelta(minutes=6)
    demo = f"My AI project presentation is today at {demo_time:%I:%M %p}. Remind me 5 minutes before."
    c1, c2 = st.columns(2)
    if c1.button("Fill demo: event in ~6 minutes"):
        st.session_state["nl_text"] = demo
    if c2.button("Fill demo: next Monday"):
        st.session_state["nl_text"] = "I have a university meeting next Monday at 10 AM. Remind me one day before and one hour before."
    text = st.text_area("Describe your event", key="nl_text", height=100,
                        placeholder="Schedule my final project presentation next Friday at 10 AM and remind me one day before.")
    if st.button("Analyze with AI", type="primary"):
        with st.spinner("Analysing..."):
            st.session_state["result"] = nlp.extract(text, datetime.now(), use_llm=use_llm)
            st.session_state["result_text"] = text

    res = st.session_state.get("result")
    if res:
        for err in res.errors:
            st.error(err)
        for w in res.warnings:
            st.warning(w)
        e = res.event
        st.caption(f"Extraction source: **{res.source}** · {res.elapsed_ms:.0f} ms")
        if e.intent != "create_event":
            st.info(f"Detected intent: **{e.intent}**. This screen only creates events; use the Events page to edit or delete.")
        else:
            st.subheader("Review & complete (you stay in control)")
            c1, c2, c3 = st.columns(3)
            title = c1.text_input("Title", e.title)
            d_default = datetime.strptime(e.date, "%Y-%m-%d").date() if e.date else None
            t_default = datetime.strptime(e.time, "%H:%M").time() if e.time else None
            date_v = c2.date_input("Date", d_default)
            time_v = c3.time_input("Time", t_default)
            c4, c5, c6, c7 = st.columns(4)
            category = c4.selectbox("Category", CATEGORIES, index=CATEGORIES.index(e.category))
            priority = c5.selectbox("Priority", PRIORITIES, index=PRIORITIES.index(e.priority))
            duration = c6.number_input("Duration (min)", 1, 1440, e.duration_minutes)
            location = c7.text_input("Location", e.location)
            rem_txt = st.text_input("Reminders (minutes before, comma-separated)", ", ".join(map(str, e.reminders)))
            if e.missing_fields:
                st.warning(f"Missing: {', '.join(e.missing_fields)} - please fill them in above.")
            with st.expander("Structured JSON produced by the AI/NLP layer"):
                st.json(e.to_dict())
                st.json(res.features)
            if st.button("Confirm & Save", type="primary"):
                try:
                    reminders = [int(x) for x in rem_txt.replace(";", ",").split(",") if x.strip()]
                    final = EventExtraction.from_dict({
                        "intent": "create_event", "title": title, "description": e.description,
                        "date": date_v.isoformat() if date_v else None,
                        "time": time_v.strftime("%H:%M") if time_v else None,
                        "duration_minutes": duration, "location": location, "category": category,
                        "priority": priority, "reminders": reminders})
                    errors, warns = validate_for_scheduling(final, datetime.now())
                    if errors:
                        for er in errors:
                            st.error(er)
                    else:
                        out = cal.create_event(final, datetime.now(), st.session_state.get("result_text", ""))
                        for w in warns:
                            st.warning(w)
                        st.success(f"Saved event #{out.event_id}. Reminders scheduled: "
                                   f"{[humanize_minutes(m) + ' before' for m in out.scheduled] or 'none'}")
                        st.session_state.pop("result", None)
                except DuplicateEventError as ex:
                    st.error(str(ex))
                except ValidationFailed as ex:
                    st.error("; ".join(ex.errors))
                except ValueError as ex:
                    st.error(f"Invalid value: {ex}")
                except DatabaseError:
                    st.error("Could not save to the database. Please try again.")
                except Exception:
                    logging.exception("Unexpected error while saving")
                    st.error("Something unexpected went wrong. Nothing was saved.")

# ================================= Events =================================
elif page == "Events":
    st.title("Calendar / Events")
    q = st.text_input("Search events", "")
    events = cal.list_events(q)
    if events:
        df = pd.DataFrame(events)[["id", "title", "start_time", "duration_minutes", "location", "category", "priority"]]
        st.dataframe(df, use_container_width=True, hide_index=True)
        chosen = st.selectbox("Select event to edit/delete", [e["id"] for e in events],
                              format_func=lambda i: next(f"#{e['id']} {e['title']} ({e['start_time']})" for e in events if e["id"] == i))
        ev = cal.get_event(chosen)
        with st.form("edit_form"):
            c1, c2 = st.columns(2)
            title = c1.text_input("Title", ev["title"])
            start = datetime.strptime(ev["start_time"], "%Y-%m-%d %H:%M")
            d = c2.date_input("Date", start.date())
            t = c2.time_input("Time", start.time())
            loc = c1.text_input("Location", ev["location"])
            cat = c1.selectbox("Category", CATEGORIES, index=CATEGORIES.index(ev["category"]) if ev["category"] in CATEGORIES else len(CATEGORIES) - 1)
            pri = c2.selectbox("Priority", PRIORITIES, index=PRIORITIES.index(ev["priority"]))
            save = st.form_submit_button("Save changes")
        if save:
            try:
                cal.update_event(chosen, {"title": title, "start_time": f"{d:%Y-%m-%d} {t:%H:%M}",
                                          "location": loc, "category": cat, "priority": pri})
                st.success("Updated.")
                st.rerun()
            except (ValidationFailed, DuplicateEventError) as ex:
                st.error("; ".join(getattr(ex, "errors", [str(ex)])))
        if st.button("Delete this event", type="secondary"):
            cal.delete_event(chosen)
            st.success("Deleted (its reminders were removed too).")
            st.rerun()
    else:
        st.info("No events found.")

# ============================= Reminder Center ============================
elif page == "Reminder Center":
    st.title("Reminder Center")
    tabs = st.tabs(["Upcoming", "Triggered", "Dismissed / Completed", "Activity log"])
    with tabs[0]:
        for r in rem.list("pending"):
            c1, c2 = st.columns([4, 1])
            c1.write(f"**{r['title']}** - {humanize_minutes(r['minutes_before'])} before · fires {r['trigger_time']} · in {due_in(r['trigger_time'])}")
            if c2.button("Dismiss", key=f"d{r['id']}"):
                rem.dismiss(r["id"]); st.rerun()
    with tabs[1]:
        for r in rem.list("triggered"):
            c1, c2, c3 = st.columns([4, 1, 1])
            c1.write(f"**{r['title']}** - alerted at {r['triggered_at']}")
            if c2.button("Complete", key=f"c{r['id']}"):
                rem.complete(r["id"]); st.rerun()
            if c3.button("Dismiss", key=f"x{r['id']}"):
                rem.dismiss(r["id"]); st.rerun()
    with tabs[2]:
        rows = rem.list("dismissed") + rem.list("completed")
        st.dataframe(pd.DataFrame(rows)[["title", "minutes_before", "status", "trigger_time"]] if rows else pd.DataFrame(), use_container_width=True)
    with tabs[3]:
        st.subheader("Notification history")
        h = notifier.history(100)
        st.dataframe(pd.DataFrame(h)[["created_at", "message"]] if h else pd.DataFrame(), use_container_width=True)
        st.subheader("Activity log")
        lg = cal.log.recent(100)
        st.dataframe(pd.DataFrame(lg)[["ts", "action", "details"]] if lg else pd.DataFrame(), use_container_width=True)

# =========================== AI Test / Evaluation =========================
elif page == "AI Test / Evaluation":
    st.title("AI Test / Evaluation")
    samples = ["Meeting with John tomorrow at 3.", "Remind me about Sarah's birthday on December 20.",
               "Set an alarm for my interview on Friday at 8 in the morning.", "Exam on 2020-01-05 at 3 PM", "asdf qwerty"]
    pick = st.selectbox("Sample commands", samples)
    text = st.text_input("Or type your own", pick)
    if st.button("Run extraction test"):
        now = datetime.now()
        r = nlp.extract(text, now, use_llm=use_llm)
        errors, warns = validate_for_scheduling(r.event, now)
        c1, c2, c3 = st.columns(3)
        c1.metric("Processing time", f"{r.elapsed_ms:.0f} ms")
        c2.metric("Source", r.source)
        c3.metric("Validation", "PASS" if not errors else "REJECT")
        st.subheader("Input"); st.code(text)
        st.subheader("AI extraction"); st.json(r.event.to_dict())
        st.subheader("Engineered NLP features"); st.json(r.features)
        for m in errors: st.error(m)
        for m in warns + r.warnings: st.warning(m)
        if r.raw_llm:
            with st.expander("Raw model output"): st.code(r.raw_llm)
    with st.expander("Active system prompt"):
        st.code(build_system_prompt(settings.prompt_version, datetime.now()))
    st.info("Full dataset evaluation: run `python -m evaluation.evaluate` (see README).")

# ================================== About =================================
else:
    st.title("About")
    st.markdown(f"""
**Problem.** People forget meetings, exams and appointments. This app lets you type an event in plain
English and automatically schedules reminders.

**AI approach.** Hybrid *LLM + NLP + controlled automation*. Claude (`{settings.anthropic_model}`,
temperature {settings.llm_temperature}) converts text to structured JSON. A deterministic rule-based
parser cross-checks dates, times and reminders and also serves as an offline fallback.

**Pipeline.** `Text → preprocessing → features → LLM JSON → schema validation → hallucination guards →
validation layer → you confirm → SQLite calendar → reminder scheduler → alert → activity log`.

**Controlled automation.** The AI only returns data. Python validates it and can only call predefined
functions (create/edit/delete event, schedule/dismiss reminder). It cannot run commands or touch files.

**Limitations.** Reminders fire only while this app is running (missed ones fire late on next start).
Ambiguous phrases ("at 3", "next Friday") are assumed and flagged for confirmation. English only.

**Responsible AI.** Human confirmation before saving, strict validation, no invented locations/reminders,
API key in `.env`, no secrets in code, calendar data stored locally; only your typed sentence is sent to
the AI provider (and only when the AI toggle is on).
""")
