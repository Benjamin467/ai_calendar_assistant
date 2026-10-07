"""Notification channels:
  1. in-app  (saved in the DB, shown by Streamlit as toast + banner)
  2. console log
  3. sound            (Windows only, via the standard-library winsound)
  4. desktop pop-up   (Windows only, via PowerShell balloon notification)
Sound and desktop channels are optional and can never crash the app.
"""
import logging
import os
import subprocess
import sys
import threading
from datetime import datetime
from typing import Any, Dict, List

import config.settings  # noqa: F401  (makes sure .env is loaded)
from database.database import Database
from database.repositories import NotificationRepository

log = logging.getLogger("alerts")


def _flag(name: str, default: bool = True) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


_PS_SCRIPT = (
    "Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing;"
    "$n = New-Object System.Windows.Forms.NotifyIcon;"
    "$n.Icon = [System.Drawing.SystemIcons]::Information;"
    "$n.BalloonTipTitle = 'AI Calendar Reminder';"
    "$n.BalloonTipText = $env:NOTIFY_MSG;"
    "$n.Visible = $true; $n.ShowBalloonTip(10000);"
    "Start-Sleep -Seconds 11; $n.Dispose()"
)


def play_sound() -> None:
    """Three short beeps in a background thread (Windows only)."""
    if sys.platform != "win32":
        return

    def _beep():
        try:
            import winsound
            for freq in (880, 1100, 1320):
                winsound.Beep(freq, 250)
        except Exception:
            log.warning("Could not play alert sound", exc_info=True)

    threading.Thread(target=_beep, daemon=True).start()


def desktop_popup(message: str) -> None:
    """Windows corner notification. The message is passed through an environment
    variable (never pasted into the command), so it cannot inject commands."""
    if sys.platform != "win32":
        return
    try:
        env = dict(os.environ, NOTIFY_MSG=message)
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", _PS_SCRIPT],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        log.warning("Could not show desktop notification", exc_info=True)


_PS_SPEAK = (
    "Add-Type -AssemblyName System.Speech;"
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        "$s.Volume = 100; for ($i = 0; $i -lt 3; $i++) { $s.Speak($env:SPEAK_MSG); Start-Sleep -Milliseconds 700 }"
)


def speak(text: str) -> None:
    """Read the alert aloud with the built-in Windows voice (Windows only)."""
    if sys.platform != "win32" or not text:
        return
    try:
        env = dict(os.environ, SPEAK_MSG=text)
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", _PS_SPEAK],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        log.warning("Could not speak alert", exc_info=True)


class NotificationService:
    def __init__(self, db: Database):
        self.repo = NotificationRepository(db)

    def send(self, reminder_id: int, event_id: int, message: str, now: datetime, spoken: str = None) -> int:
        nid = self.repo.add(reminder_id, event_id, message, now)
        log.info("ALERT: %s", message)
        print(f"[ALERT {now:%H:%M:%S}] {message}")
        if _flag("ENABLE_SOUND"):
            play_sound()
        if _flag("ENABLE_DESKTOP_NOTIFICATIONS"):
            desktop_popup(message)
        if _flag("ENABLE_VOICE"):
            speak(spoken or message)
        return nid

    def unseen(self) -> List[Dict[str, Any]]:
        return self.repo.unseen()

    def mark_seen(self, ids: List[int]) -> None:
        self.repo.mark_seen(ids)

    def history(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self.repo.history(limit)