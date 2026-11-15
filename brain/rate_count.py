"""
Counts E.V.E.'s requests to Gemini, so the HUD can show how many are left.

Google's free plan allows a set number of requests a MINUTE (15 by
default; change it with EVE_GEMINI_PER_MINUTE=15 in .env). "A minute" is a
sliding window: a request stops counting 60 seconds after it was sent.

What one question costs:
    a plain question                    1
    "open Spotify", "set a timer"       1 (quick replies)
    weather, Wikipedia, look at screen  2 (use the tool, then answer)
    hide, start fresh, chat log...      0 (handled without Gemini)

It also keeps a total for today, saved in data/gemini_count.json, so it
survives restarts. (The free plan has a daily limit too.)

This is E.V.E.'s OWN count: if the same API key is used somewhere else,
Google counts those requests but she can't see them.

Test it alone:   .venv\\Scripts\\python -m brain.rate_count
"""

import json
import logging
import math
import os
import threading
import time
from collections import deque
from datetime import date

from paths import DATA_DIR

COUNT_FILE = DATA_DIR / "gemini_count.json"
WINDOW = 60   # seconds


def _per_minute() -> int:
    try:
        return max(1, int(os.getenv("EVE_GEMINI_PER_MINUTE", "15")))
    except ValueError:
        return 15


diary = logging.getLogger("eve")


class RateCount:
    def __init__(self, path=COUNT_FILE):
        self.path = path
        self.per_minute = _per_minute()
        # The brain counts on a background thread; the HUD reads on its own.
        self._lock = threading.Lock()
        self._sent: deque[float] = deque()   # when each recent request was sent (time.monotonic())
        self._day, self._today = self._load()

    def note(self) -> None:
        """Call once for every request actually sent to Gemini."""
        with self._lock:
            self._sent.append(time.monotonic())
            today = date.today().isoformat()
            if today != self._day:
                self._day, self._today = today, 0
            self._today += 1
            self._save()

    def left(self) -> int:
        """Requests left in the last 60 seconds (never below 0)."""
        with self._lock:
            self._forget_old()
            return max(0, self.per_minute - len(self._sent))

    def seconds_until_free(self) -> int:
        """0 if a request can be sent now; otherwise how long until one can."""
        with self._lock:
            self._forget_old()
            if len(self._sent) < self.per_minute:
                return 0
            oldest = self._sent[len(self._sent) - self.per_minute]
            return max(1, math.ceil(oldest + WINDOW - time.monotonic()))

    def today(self) -> int:
        with self._lock:
            return self._today if self._day == date.today().isoformat() else 0

    def _forget_old(self) -> None:
        cutoff = time.monotonic() - WINDOW
        while self._sent and self._sent[0] < cutoff:
            self._sent.popleft()

    # --- Today's total, kept in a small file -----------------------------

    def _load(self) -> tuple[str, int]:
        today = date.today().isoformat()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("date") == today:
                return today, int(data.get("count", 0))
        except (OSError, ValueError, AttributeError, TypeError):
            pass   # missing or damaged: start today's count from 0
        return today, 0

    def _save(self) -> None:
        try:
            self.path.write_text(json.dumps({"date": self._day, "count": self._today}), encoding="utf-8")
        except OSError as error:
            diary.warning(f"Couldn't save the Gemini count: {error}")


_shared: RateCount | None = None


def get_rate_count() -> RateCount:
    """The one shared count, used by both the brain and the HUD."""
    global _shared
    if _shared is None:
        _shared = RateCount()
    return _shared


if __name__ == "__main__":
    count = RateCount()
    print(f"Limit: {count.per_minute} a minute.  Today so far: {count.today()}")
