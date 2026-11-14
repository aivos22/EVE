"""
E.V.E.'s diary: everything that shows in the HUD's log feed, plus full
details of any problem, saved to a text file with the time.

One file per day, in data/logs/, for example:
    data/logs/eve_2026-11-14.txt

    18:42:07  INFO    === E.V.E. started ===
    18:42:31  INFO    [VOICE] Heard: what's the weather like?
    18:42:32  INFO    [ACTION] Checking weather: Berkhamsted
    18:43:10  WARNING [BRAIN] Can't reach Gemini: no internet connection

This uses Python's built-in `logging` module. Any file can write to the
diary with:
    from log_file import log
    log.warning("Something went wrong")

Files older than KEEP_DAYS are deleted at start-up, so they never pile up.
(They stay on this PC: data/ is never uploaded to GitHub.)
"""

import logging
import sys
import threading
import time
from datetime import date

from paths import DATA_DIR

LOG_DIR = DATA_DIR / "logs"
KEEP_DAYS = 14

# The diary's "logger". Everything E.V.E. writes goes through this.
log = logging.getLogger("eve")


def start_log_file():
    """Open today's diary file and start writing to it. Returns its path."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    _delete_old_files()

    path = LOG_DIR / f"eve_{date.today():%Y-%m-%d}.txt"
    handler = logging.FileHandler(path, encoding="utf-8")   # adds to the file, never overwrites
    handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s", "%H:%M:%S"))

    # The "root" logger also hears from the libraries we use (Qt, Gemini,
    # Whisper...). From them we only want real problems, not chatter...
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.WARNING)
    # ...but from E.V.E. herself we want everything, including normal activity.
    log.setLevel(logging.INFO)

    # Crashes that nobody caught would normally just print to the terminal
    # and vanish. These "hooks" send them to the diary too, with full details.
    sys.excepthook = _log_crash
    threading.excepthook = lambda info: _log_crash(info.exc_type, info.exc_value, info.exc_traceback)

    log.info("=== E.V.E. started ===")
    return path


def log_line(message: str, source: str = "EVE") -> None:
    """Save a line from the HUD's log feed, e.g. log_line("Heard: hi", "VOICE")."""
    log.info(f"[{source}] {message}")


def _log_crash(exc_type, exc_value, exc_traceback) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        return   # pressing Ctrl+C in the terminal isn't a crash
    log.critical("Uncaught error", exc_info=(exc_type, exc_value, exc_traceback))
    sys.__excepthook__(exc_type, exc_value, exc_traceback)   # still show it in the terminal


def _delete_old_files() -> None:
    cutoff = time.time() - KEEP_DAYS * 24 * 60 * 60
    for old in LOG_DIR.glob("eve_*.txt"):
        if old.stat().st_mtime < cutoff:   # last changed before the cutoff
            old.unlink(missing_ok=True)
