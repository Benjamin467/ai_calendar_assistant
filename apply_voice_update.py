"""Run once from the project folder:  python apply_voice_update.py
Adds: spoken voice alerts + a 'Sport' category (fixes Football Training = Travel)."""
from pathlib import Path

def patch(path, old, new, marker):
    p = Path(path)
    s = p.read_text(encoding="utf-8")
    if marker in s:
        print(f"already updated: {path}")
        return
    if old not in s:
        raise SystemExit(f"Could not patch {path}: expected text not found. Send me this file.")
    p.write_text(s.replace(old, new, 1), encoding="utf-8")
    print(f"updated: {path}")

# 1. new category
patch("models/schemas.py", '"Social", "Travel", "General")', '"Social", "Sport", "Travel", "General")', '"Sport"')

# 2. sport keywords
patch("nlp/lexicon.py", '    ("Travel", [',
      '    ("Sport", ["sport", "sports", "football", "soccer", "basketball", "gym", "workout", "training", "exercise"]),\n    ("Travel", [',
      '("Sport"')

# 3. whole-word keyword matching ("train" no longer matches "training")
patch("nlp/rules.py", 'if re.search(rf"\\b{re.escape(kw)}", low):',
      'if re.search(rf"\\b{re.escape(kw)}(?:s|es)?\\b", low):', '(?:s|es)?')

# 4. voice
patch("services/notification_service.py", "class NotificationService:", '''_PS_SPEAK = (
    "Add-Type -AssemblyName System.Speech;"
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
    "$s.Volume = 100; $s.Speak($env:SPEAK_MSG)"
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


class NotificationService:''', "def speak(")
patch("services/notification_service.py",
      "def send(self, reminder_id: int, event_id: int, message: str, now: datetime) -> int:",
      "def send(self, reminder_id: int, event_id: int, message: str, now: datetime, spoken: str = None) -> int:",
      "spoken: str = None")
patch("services/notification_service.py",
      "            desktop_popup(message)\n        return nid",
      "            desktop_popup(message)\n        if _flag(\"ENABLE_VOICE\"):\n            speak(spoken or message)\n        return nid",
      "ENABLE_VOICE")

patch("services/reminder_service.py", "    def check_due(self, now: Optional[datetime] = None) -> List[str]:",
      '''    def build_spoken(self, r: Dict[str, Any], now: datetime) -> str:
        start = datetime.strptime(r["start_time"], "%Y-%m-%d %H:%M")
        if start <= now or r["minutes_before"] == 0:
            return f"Attention. It is time for {r['title']}."
        return f"Reminder. {r['title']} starts in {humanize_minutes(r['minutes_before'])}."

    def check_due(self, now: Optional[datetime] = None) -> List[str]:''', "def build_spoken")
patch("services/reminder_service.py",
      'self.notifier.send(r["id"], r["event_id"], msg, now)',
      'self.notifier.send(r["id"], r["event_id"], msg, now, self.build_spoken(r, now))',
      "self.build_spoken(r, now))")
print("\nAll done. Now restart the app.")
