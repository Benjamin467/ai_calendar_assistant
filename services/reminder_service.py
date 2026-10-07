"""Reminder checking + background scheduler (stdlib threading, no extra library)."""
import logging
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from database.database import Database
from database.repositories import LogRepository, ReminderRepository
from services.notification_service import NotificationService

log = logging.getLogger(__name__)


def humanize_minutes(m: int) -> str:
    if m % 10080 == 0 and m >= 10080:
        n, u = m // 10080, "week"
    elif m % 1440 == 0 and m >= 1440:
        n, u = m // 1440, "day"
    elif m % 60 == 0 and m >= 60:
        n, u = m // 60, "hour"
    else:
        n, u = m, "minute"
    return f"{n} {u}{'' if n == 1 else 's'}"


class ReminderService:
    def __init__(self, db: Database, notifier: NotificationService):
        self.reminders = ReminderRepository(db)
        self.log = LogRepository(db)
        self.notifier = notifier

    def build_message(self, r: Dict[str, Any], now: datetime) -> str:
        start = datetime.strptime(r["start_time"], "%Y-%m-%d %H:%M")
        if start <= now:
            return f"Reminder (late): {r['title']} has already started ({r['start_time']})."
        if r["minutes_before"] == 0:
            return f"Reminder: {r['title']} starts now."
        return f"Reminder: {r['title']} starts in {humanize_minutes(r['minutes_before'])}."

    def build_spoken(self, r: Dict[str, Any], now: datetime) -> str:
        start = datetime.strptime(r["start_time"], "%Y-%m-%d %H:%M")
        if start <= now or r["minutes_before"] == 0:
            return f"Attention. It is time for {r['title']}."
        return f"Reminder. {r['title']} starts in {humanize_minutes(r['minutes_before'])}."

    def check_due(self, now: Optional[datetime] = None) -> List[str]:
        """Fire every due reminder exactly once. Safe to call repeatedly / concurrently."""
        now = now or datetime.now()
        fired: List[str] = []
        for r in self.reminders.due(now):
            if not self.reminders.claim(r["id"], now):
                continue  # someone else already fired it
            msg = self.build_message(r, now)
            self.notifier.send(r["id"], r["event_id"], msg, now, self.build_spoken(r, now))
            self.log.add("reminder_triggered", f"reminder #{r['id']}: {msg}", now)
            fired.append(msg)
        return fired

    def dismiss(self, reminder_id: int) -> bool:
        ok = self.reminders.set_status(reminder_id, "dismissed", ("pending", "triggered"))
        if ok:
            self.log.add("reminder_dismissed", f"#{reminder_id}", datetime.now())
        return ok

    def complete(self, reminder_id: int) -> bool:
        ok = self.reminders.set_status(reminder_id, "completed", ("triggered",))
        if ok:
            self.log.add("reminder_completed", f"#{reminder_id}", datetime.now())
        return ok

    def list(self, status: Optional[str] = None):
        return self.reminders.listing(status)


class ReminderScheduler:
    """Daemon thread that calls check_due() every `interval` seconds.
    Limitation: it only runs while the application process is running; reminders
    that became due while the app was closed fire (marked 'late') at next start."""

    def __init__(self, service: ReminderService, interval: int = 10):
        self.service, self.interval = service, interval
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="reminder-scheduler", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.service.check_due()
            except Exception:  # never let the thread die
                log.exception("Scheduler tick failed")
            self._stop.wait(self.interval)

    def stop(self) -> None:
        self._stop.set()
