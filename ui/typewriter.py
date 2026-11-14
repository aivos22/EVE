"""
The typewriter effect for E.V.E.'s caption: her sentence appears letter by
letter, spread over the time she takes to say it, so the words keep pace
with her voice.

Like EventLog, this holds no widget. It works out how much of the text
should be showing, and sends that out through `text_changed`:

    typewriter.type("Good evening, sir.", 1.4)   # types it out over 1.4 seconds
    typewriter.clear()                            # wipe it (e.g. you started talking)
"""

import time

from PySide6.QtCore import QObject, QTimer, Signal

TICK_MS = 30            # how often the shown text is updated (about 33 times a second)
MIN_CHARS_PER_SEC = 12  # never slower than this, even if the audio length is odd
FALLBACK_SECONDS = 0.04 # per letter, if we're not told how long she takes


class Typewriter(QObject):
    # (text shown so far, the rest still to come). The window draws the rest
    # invisibly, so the words are already in their final places and the
    # centred caption doesn't slide sideways as letters appear.
    text_changed = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ""          # the whole sentence being typed
        self._started = 0.0      # when typing began (in seconds, from time.monotonic)
        self._duration = 0.0     # how long the typing should take
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def type(self, text: str, seconds: float = 0.0) -> None:
        """Start typing `text`, finishing after `seconds` (0 = a sensible default speed)."""
        self._text = text
        if seconds <= 0:
            seconds = len(text) * FALLBACK_SECONDS
        # Don't crawl: cap how long a sentence may take to appear.
        self._duration = min(seconds, len(text) / MIN_CHARS_PER_SEC)
        # time.monotonic() is a clock that only ever goes forward, good for measuring.
        self._started = time.monotonic()
        self._timer.start(TICK_MS)
        self._tick()

    def clear(self) -> None:
        self._timer.stop()
        self._text = ""
        self.text_changed.emit("", "")

    def _tick(self) -> None:
        elapsed = time.monotonic() - self._started
        # What fraction of the time has passed, from 0 (just started) to 1 (done).
        progress = 1.0 if self._duration <= 0 else min(elapsed / self._duration, 1.0)
        shown = round(len(self._text) * progress)
        if progress >= 1.0:
            self._timer.stop()
        self.text_changed.emit(self._text[:shown], self._text[shown:])
