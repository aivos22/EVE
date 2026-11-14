"""
Timers: "set a timer for 10 minutes", "a pasta timer for 8 minutes".

The timers run inside E.V.E. herself, on a small background thread that
checks the clock four times a second. Gemini is only needed to SET one
(turning your words into "8 minutes, label pasta"). After that it counts
down and goes off with no internet at all.

The timer keeper knows nothing about the HUD or the voice. Other code asks
to be told when something happens:
    keeper = get_timers()
    keeper.when_set(lambda timer: ...)    # e.g. get her announcement ready
    keeper.when_done(lambda timer: ...)   # e.g. flash the eye and speak

Timers last until they go off or E.V.E. closes (they aren't saved).

Test it alone:   .venv\\Scripts\\python -m actions timer 5 pasta
"""

import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

MAX_TIMERS = 10
LONGEST = 24 * 60 * 60   # seconds: one day
MAX_LABEL = 30           # characters
CHECK_EVERY = 0.25       # seconds between looks at the clock

diary = logging.getLogger("eve")


@dataclass
class Timer:
    number: int        # 1, 2, 3... so sir can say "cancel timer 2"
    label: str         # "pasta", or "" for a plain timer
    seconds: int       # how long it was set for
    ends: float        # when it goes off, on time.monotonic()'s clock

    def seconds_left(self) -> float:
        return max(0.0, self.ends - time.monotonic())

    def name(self) -> str:
        """'pasta timer', or 'timer' if it has no label."""
        return f"{self.label} timer" if self.label else "timer"

    def announcement(self) -> str:
        """What she says when it goes off."""
        return announcement_for(self.label)


def announcement_for(label: str = "") -> str:
    """'Sir, your pasta timer is done.' (or just 'your timer' with no label)."""
    return f"Sir, your {label + ' ' if label else ''}timer is done."


class TimerKeeper:
    def __init__(self):
        self._timers: list[Timer] = []
        # A "lock": the tools (brain thread), the HUD panel (main thread) and
        # the checker (its own thread) all use the list, so only one at a time.
        self._lock = threading.Lock()
        self._on_set = []
        self._on_done = []
        self._thread = None

    # --- Being told when things happen -----------------------------------

    def when_set(self, callback) -> None:
        self._on_set.append(callback)

    def when_done(self, callback) -> None:
        self._on_done.append(callback)

    # --- Changing timers --------------------------------------------------

    def add(self, seconds: int, label: str = "") -> Timer:
        """Start a timer. Raises ValueError with a plain reason if it can't."""
        if seconds < 1:
            raise ValueError("the timer needs a length, like 10 minutes")
        if seconds > LONGEST:
            raise ValueError("timers can be at most 24 hours long")
        label = tidy_label(label)
        with self._lock:
            if len(self._timers) >= MAX_TIMERS:
                raise ValueError(f"there are already {MAX_TIMERS} timers running")
            # A new number one higher than any running; back to 1 when none are left.
            number = max((t.number for t in self._timers), default=0) + 1
            timer = Timer(number, label, seconds, time.monotonic() + seconds)
            self._timers.append(timer)
            if self._thread is None:
                # (Python's "daemon" threads stop by themselves when the program closes.)
                self._thread = threading.Thread(target=self._watch, daemon=True)
                self._thread.start()
        self._tell(self._on_set, timer)
        return timer

    def cancel(self, which: str = "") -> list[Timer]:
        """
        Stop timers. `which` is a label ("pasta"), a number ("2"), "all", or
        empty (only allowed when exactly one is running). Returns the stopped
        timers. Raises ValueError with a plain reason if it isn't clear which.
        """
        with self._lock:
            chosen = self._choose(which)
            for timer in chosen:
                self._timers.remove(timer)
        return chosen

    def running(self) -> list[Timer]:
        """The running timers, soonest first."""
        with self._lock:
            return sorted(self._timers, key=lambda t: t.ends)

    # --- Inside -----------------------------------------------------------

    def _choose(self, which: str) -> list[Timer]:
        which = which.strip().lower()
        if not self._timers:
            raise ValueError("there are no timers running")
        if which in ("all", "every", "everything", "all timers"):
            return list(self._timers)
        if not which:
            if len(self._timers) == 1:
                return list(self._timers)
            raise ValueError(f"there are {len(self._timers)} timers running, so say which one")
        number = re.sub(r"\D", "", which)
        if number and which.replace("timer", "").replace("number", "").strip(" #") == number:
            found = [t for t in self._timers if t.number == int(number)]
        else:
            found = [t for t in self._timers if t.label == tidy_label(which)]
        if not found:
            raise ValueError(f"there's no timer called {which}")
        return found

    def _watch(self) -> None:
        """The checker thread: four times a second, set off any timer that's due."""
        while True:
            time.sleep(CHECK_EVERY)
            with self._lock:
                due = [t for t in self._timers if t.seconds_left() <= 0]
                for timer in due:
                    self._timers.remove(timer)
            for timer in due:
                self._tell(self._on_done, timer)

    @staticmethod
    def _tell(callbacks, timer: Timer) -> None:
        for callback in callbacks:
            try:
                callback(timer)
            except Exception:   # one broken listener mustn't stop the others, or the checker
                diary.exception(f"Timer callback failed for {timer.name()}")


_keeper: TimerKeeper | None = None


def get_timers() -> TimerKeeper:
    """The one shared timer keeper, used by the tools, the HUD and the voice."""
    global _keeper
    if _keeper is None:
        _keeper = TimerKeeper()
    return _keeper


# --- Words ----------------------------------------------------------------

def tidy_label(label: str) -> str:
    """'My Pasta timer!' -> 'pasta'. Lower case, no 'timer', no 'my/the/a'."""
    words = re.sub(r"[^a-z0-9' ]", " ", label.lower()).split()
    while words and words[0] in ("my", "the", "a", "an"):
        words.pop(0)
    words = [w for w in words if w not in ("timer", "timers")]
    return " ".join(words)[:MAX_LABEL].strip()


def say_duration(seconds: float) -> str:
    """483 -> '8 minutes 3 seconds'. Written for speaking, so no '08:03'."""
    seconds = int(round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    parts = []
    for amount, unit in ((hours, "hour"), (minutes, "minute"), (secs, "second")):
        if amount:
            parts.append(f"{amount} {unit}" + ("s" if amount != 1 else ""))
    return " ".join(parts) or "0 seconds"


def clock_time(seconds_from_now: float) -> str:
    """When something will happen, like '6:42 pm'."""
    when = datetime.now() + timedelta(seconds=seconds_from_now)
    return f"{when:%I}".lstrip("0") + f":{when:%M} " + ("am" if when.hour < 12 else "pm")


# --- The tools Gemini can use -----------------------------------------------

def set_timer(hours: int = 0, minutes: int = 0, seconds: int = 0, label: str = "") -> dict:
    """
    Start a countdown timer. Use it when sir asks for a timer or a reminder in
    a set amount of time, e.g. "set a timer for 10 minutes" or "a pasta timer
    for 8 minutes". You announce it out loud yourself when it finishes, so
    just confirm it's set. Several timers can run at once.

    Args:
        hours: Hours, if any.
        minutes: Minutes, if any. "An hour and a half" is hours 1, minutes 30.
        seconds: Seconds, if any.
        label: A short name if sir gave one, e.g. "pasta". Otherwise leave empty.
    """
    total = round(float(hours or 0) * 3600 + float(minutes or 0) * 60 + float(seconds or 0))
    try:
        timer = get_timers().add(total, label)
    except ValueError as problem:
        return {"error": str(problem)}
    return {"set": timer.name(), "number": timer.number,
            "length": say_duration(timer.seconds), "goes_off_at": clock_time(timer.seconds)}


def cancel_timer(which: str = "") -> dict:
    """
    Stop a running timer before it goes off. Use it when sir asks to cancel,
    stop or clear a timer.

    Args:
        which: The timer's label (e.g. "pasta"), its number (e.g. "2"), or "all".
            Leave empty if only one timer is running.
    """
    try:
        stopped = get_timers().cancel(which)
    except ValueError as problem:
        return {"error": str(problem), "running": [t.name() for t in get_timers().running()]}
    return {"cancelled": [t.name() for t in stopped], "still_running": len(get_timers().running())}


def list_timers() -> dict:
    """
    List the running timers and how long each has left. Use it when sir asks
    about his timers, e.g. "how long's left on the pasta?".
    """
    timers = get_timers().running()
    if not timers:
        return {"timers": "none running"}
    return {"timers": [{"number": t.number, "name": t.name(), "left": say_duration(t.seconds_left()),
                        "goes_off_at": clock_time(t.seconds_left())} for t in timers]}
