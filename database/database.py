"""SQLite access. One shared connection guarded by a lock so the background
scheduler thread and the Streamlit thread can both use it safely."""
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Sequence


class DatabaseError(Exception):
    pass


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    start_time TEXT NOT NULL,              -- 'YYYY-MM-DD HH:MM' (local time)
    duration_minutes INTEGER NOT NULL DEFAULT 60,
    location TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'General',
    priority TEXT NOT NULL DEFAULT 'Medium',
    source_text TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (title, start_time)             -- duplicate prevention
);
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    minutes_before INTEGER NOT NULL,
    trigger_time TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending', -- pending | triggered | completed | dismissed
    triggered_at TEXT,
    UNIQUE (event_id, minutes_before)      -- no duplicate reminders
);
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reminder_id INTEGER,
    event_id INTEGER,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    seen INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    action TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(status, trigger_time);
"""


class Database:
    def __init__(self, path: str = ":memory:"):
        self.path = str(path)
        try:
            if self.path != ":memory:":
                Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            self._lock = threading.RLock()
            self._conn = sqlite3.connect(self.path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.executescript(SCHEMA)
            self._conn.commit()
        except sqlite3.Error as e:
            raise DatabaseError(f"Could not open the database: {e}") from e

    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            try:
                cur = self._conn.execute(sql, params)
                self._conn.commit()
                return cur
            except sqlite3.IntegrityError:
                self._conn.rollback()
                raise
            except sqlite3.Error as e:
                self._conn.rollback()
                raise DatabaseError(f"Database operation failed: {e}") from e

    def query(self, sql: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
        with self._lock:
            try:
                return [dict(r) for r in self._conn.execute(sql, params).fetchall()]
            except sqlite3.Error as e:
                raise DatabaseError(f"Database query failed: {e}") from e

    def close(self):
        with self._lock:
            self._conn.close()
