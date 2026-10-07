"""Repositories = the ONLY place SQL lives. All queries are parameterised."""
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

from database.database import Database

FMT = "%Y-%m-%d %H:%M"


def fmt(dt: datetime) -> str:
    return dt.strftime(FMT)


class DuplicateEventError(Exception):
    pass


class EventRepository:
    def __init__(self, db: Database):
        self.db = db

    def add(self, e: Dict[str, Any], now: datetime) -> int:
        try:
            cur = self.db.execute(
                "INSERT INTO events (title, description, start_time, duration_minutes, location,"
                " category, priority, source_text, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (e["title"], e.get("description", ""), e["start_time"], e.get("duration_minutes", 60),
                 e.get("location", ""), e.get("category", "General"), e.get("priority", "Medium"),
                 e.get("source_text", ""), fmt(now)))
        except sqlite3.IntegrityError:
            raise DuplicateEventError("An event with the same title and start time already exists.")
        return cur.lastrowid

    def get(self, event_id: int) -> Optional[Dict[str, Any]]:
        rows = self.db.query("SELECT * FROM events WHERE id=?", (event_id,))
        return rows[0] if rows else None

    def list(self, search: str = "") -> List[Dict[str, Any]]:
        if search.strip():
            like = f"%{search.strip()}%"
            return self.db.query(
                "SELECT * FROM events WHERE title LIKE ? OR description LIKE ? OR category LIKE ?"
                " OR location LIKE ? ORDER BY start_time", (like, like, like, like))
        return self.db.query("SELECT * FROM events ORDER BY start_time")

    def between(self, start: str, end: str) -> List[Dict[str, Any]]:
        return self.db.query("SELECT * FROM events WHERE start_time>=? AND start_time<? ORDER BY start_time",
                             (start, end))

    def update(self, event_id: int, fields: Dict[str, Any]) -> None:
        allowed = {"title", "description", "start_time", "duration_minutes", "location", "category", "priority"}
        cols = [k for k in fields if k in allowed]
        if not cols:
            return
        sql = "UPDATE events SET " + ", ".join(f"{c}=?" for c in cols) + " WHERE id=?"
        try:
            self.db.execute(sql, [fields[c] for c in cols] + [event_id])
        except sqlite3.IntegrityError:
            raise DuplicateEventError("Another event already has that title and start time.")

    def delete(self, event_id: int) -> bool:
        return self.db.execute("DELETE FROM events WHERE id=?", (event_id,)).rowcount > 0


class ReminderRepository:
    def __init__(self, db: Database):
        self.db = db

    def add(self, event_id: int, minutes_before: int, trigger: datetime) -> Optional[int]:
        try:
            return self.db.execute(
                "INSERT INTO reminders (event_id, minutes_before, trigger_time) VALUES (?,?,?)",
                (event_id, minutes_before, fmt(trigger))).lastrowid
        except sqlite3.IntegrityError:
            return None  # duplicate reminder silently ignored

    def for_event(self, event_id: int) -> List[Dict[str, Any]]:
        return self.db.query("SELECT * FROM reminders WHERE event_id=? ORDER BY minutes_before DESC", (event_id,))

    def listing(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        sql = ("SELECT r.*, e.title, e.start_time FROM reminders r JOIN events e ON e.id=r.event_id")
        params: tuple = ()
        if status:
            sql += " WHERE r.status=?"
            params = (status,)
        return self.db.query(sql + " ORDER BY r.trigger_time", params)

    def due(self, now: datetime) -> List[Dict[str, Any]]:
        return self.db.query(
            "SELECT r.*, e.title, e.start_time FROM reminders r JOIN events e ON e.id=r.event_id"
            " WHERE r.status='pending' AND r.trigger_time<=? ORDER BY r.trigger_time", (fmt(now),))

    def claim(self, reminder_id: int, now: datetime) -> bool:
        """Atomically pending -> triggered. Only ONE caller can win (no duplicate alerts)."""
        cur = self.db.execute(
            "UPDATE reminders SET status='triggered', triggered_at=? WHERE id=? AND status='pending'",
            (fmt(now), reminder_id))
        return cur.rowcount == 1

    def set_status(self, reminder_id: int, status: str, only_from: tuple) -> bool:
        q = ",".join("?" * len(only_from))
        cur = self.db.execute(f"UPDATE reminders SET status=? WHERE id=? AND status IN ({q})",
                              (status, reminder_id, *only_from))
        return cur.rowcount == 1

    def retime(self, event_id: int, start: datetime) -> None:
        from datetime import timedelta
        for r in self.for_event(event_id):
            if r["status"] == "pending":
                self.db.execute("UPDATE reminders SET trigger_time=? WHERE id=?",
                                (fmt(start - timedelta(minutes=r["minutes_before"])), r["id"]))


class NotificationRepository:
    def __init__(self, db: Database):
        self.db = db

    def add(self, reminder_id: Optional[int], event_id: Optional[int], message: str, now: datetime) -> int:
        return self.db.execute(
            "INSERT INTO notifications (reminder_id, event_id, message, created_at) VALUES (?,?,?,?)",
            (reminder_id, event_id, message, fmt(now))).lastrowid

    def unseen(self) -> List[Dict[str, Any]]:
        return self.db.query("SELECT * FROM notifications WHERE seen=0 ORDER BY id")

    def mark_seen(self, ids: List[int]) -> None:
        for i in ids:
            self.db.execute("UPDATE notifications SET seen=1 WHERE id=?", (i,))

    def history(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self.db.query("SELECT * FROM notifications ORDER BY id DESC LIMIT ?", (limit,))


class LogRepository:
    def __init__(self, db: Database):
        self.db = db

    def add(self, action: str, details: str, now: datetime) -> None:
        self.db.execute("INSERT INTO activity_log (ts, action, details) VALUES (?,?,?)",
                        (fmt(now), action, details[:500]))

    def recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self.db.query("SELECT * FROM activity_log ORDER BY id DESC LIMIT ?", (limit,))
