"""
The speech log: the last 10 chats between sir and E.V.E., saved on this PC.

Each chat is one thing sir said and her reply, with the time:
    {"time": "2026-11-15T14:02:11", "you": "what's the weather", "eve": "Light rain, sir."}

They're kept in data/chat_log.json (a plain text file you can open; data/
is never uploaded to GitHub). Only the newest KEEP chats are kept: when an
11th arrives, the oldest drops off.

Two jobs:
  1. You can read it: the L key (or the LOG button) shows it on the HUD.
  2. Picking up where you left off: when E.V.E. starts, if the last chat
     was less than RELOAD_HOURS ago she reloads the chats into her
     short-term memory. Older than that, she starts fresh (but the log is
     still there to read).

"Eve, start fresh" doesn't delete the log; it puts a marker in it
("fresh_from"), so the chats before it are never reloaded.

Test it alone:   .venv\\Scripts\\python -m brain.chat_log
"""

import json
import logging
import os
import threading
from datetime import datetime, timedelta

from paths import DATA_DIR

LOG_FILE = DATA_DIR / "chat_log.json"
KEEP = 10            # how many chats are kept
RELOAD_HOURS = 6     # reload them at start-up only if the last one is newer than this
MAX_LENGTH = 2000    # characters per line, so one huge reply can't bloat the file

diary = logging.getLogger("eve")


class ChatLog:
    def __init__(self, path=LOG_FILE):
        self.path = path
        # The brain adds chats on a background thread while the HUD reads
        # them on its own thread; the lock stops them getting in each other's way.
        self._lock = threading.Lock()
        self.version = 0   # goes up on every change, so the HUD knows to redraw
        self.chats, self.fresh_from = self._load()

    # --- Reading --------------------------------------------------------

    def all(self) -> list[dict]:
        """A copy of every chat, oldest first."""
        with self._lock:
            return [dict(chat) for chat in self.chats]

    def to_reload(self) -> list[dict]:
        """
        The chats to put back in her memory at start-up: only if the last
        one is less than RELOAD_HOURS old, and only those after the last
        "start fresh".
        """
        with self._lock:
            chats = [chat for chat in self.chats if chat["time"] > self.fresh_from]
        if not chats:
            return []
        last = _when(chats[-1]["time"])
        if last is None or datetime.now() - last > timedelta(hours=RELOAD_HOURS):
            return []
        return chats

    # --- Changing -------------------------------------------------------

    def add(self, you: str, eve: str) -> None:
        """Save one chat. Never raises: a problem is written in the diary instead."""
        chat = {"time": _now(), "you": you.strip()[:MAX_LENGTH], "eve": eve.strip()[:MAX_LENGTH]}
        with self._lock:
            self.chats.append(chat)
            self.chats = self.chats[-KEEP:]   # keep only the newest KEEP
            self._save()

    def mark_fresh_start(self) -> None:
        """'Start fresh': the chats so far stay readable but are never reloaded."""
        with self._lock:
            self.fresh_from = _now()
            self._save()

    def clear(self) -> int:
        """Delete every chat. Returns how many there were."""
        with self._lock:
            count = len(self.chats)
            self.chats = []
            self.fresh_from = ""
            self._save()
            return count

    # --- The file -------------------------------------------------------

    def _load(self) -> tuple[list[dict], str]:
        if not self.path.exists():
            return [], ""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            chats = [chat for chat in data.get("chats", [])
                     if isinstance(chat, dict) and {"time", "you", "eve"} <= chat.keys()]
            return chats[-KEEP:], str(data.get("fresh_from", ""))
        except (OSError, ValueError, AttributeError) as error:
            # A damaged file: keep a copy to look at, and start a new log.
            diary.warning(f"Chat log couldn't be read ({error}); starting a new one")
            try:
                self.path.replace(self.path.with_suffix(".damaged.json"))
            except OSError:
                pass
            return [], ""

    def _save(self) -> None:
        """Write the file (call with the lock held). A failure is logged, never raised."""
        self.version += 1
        try:
            # Write a temporary file, then swap it in, so a crash halfway
            # through can't leave a half-written log.
            temp = self.path.with_suffix(".writing")
            text = json.dumps({"fresh_from": self.fresh_from, "chats": self.chats},
                              indent=2, ensure_ascii=False)
            temp.write_text(text, encoding="utf-8")
            os.replace(temp, self.path)
        except OSError as error:
            diary.warning(f"Chat log couldn't be saved: {error}")


def _now() -> str:
    # Times are written like 2026-11-15T14:02:11, so comparing them as text
    # also compares them as times.
    return datetime.now().isoformat(timespec="seconds")


def _when(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def nice_time(text: str) -> str:
    """'2026-11-15T14:02:11' -> '14:02' today, or 'Sat 14:02' on another day."""
    when = _when(text)
    if when is None:
        return "?"
    if when.date() == datetime.now().date():
        return when.strftime("%H:%M")
    return when.strftime("%a %H:%M")


_shared: ChatLog | None = None


def get_chat_log() -> ChatLog:
    """The one shared log, used by both the brain and the HUD."""
    global _shared
    if _shared is None:
        _shared = ChatLog()
    return _shared


if __name__ == "__main__":
    # Show what's saved:  .venv\Scripts\python -m brain.chat_log
    log = ChatLog()
    print(f"{len(log.chats)} chats in {log.path}")
    for chat in log.chats:
        print(f"{nice_time(chat['time'])}  YOU  {chat['you']}")
        print(f"       EVE  {chat['eve']}")
    reload = log.to_reload()
    print(f"\nWould reload at start-up: {len(reload)} chats "
          f"(only if the last is under {RELOAD_HOURS} hours old, and after any 'start fresh')")
