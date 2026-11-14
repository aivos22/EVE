"""
E.V.E.'s log feed: a short, scrolling list of what she's doing.

Like the animator, this holds no widget. It keeps the lines, types new
ones out a letter at a time, and sends the text to whoever displays it
through the `text_changed` signal. Any code can add a line:

    event_log.log("Standing by")              ->  [EVE] Standing by
    event_log.log("Mic connected", "VOICE")   ->  [VOICE] Mic connected
"""

from collections import deque

from PySide6.QtCore import QObject, QTimer, Signal

MAX_LINES = 5          # how many lines stay on screen
TYPE_SPEED_MS = 25     # time between letters
LINE_PAUSE_MS = 250    # pause after each line
CATCH_UP_AT = 3        # if this many lines are waiting, skip the typing to catch up


class EventLog(QObject):
    text_changed = Signal(str)   # the full text to show (all visible lines)
    queue_empty = Signal()       # everything waiting has been typed out

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lines: deque[str] = deque(maxlen=MAX_LINES)   # finished lines; old ones drop off
        self._waiting: deque[str] = deque()                  # lines not typed yet
        self._typing = ""                                    # the line being typed
        self._shown = 0                                      # letters of it shown so far
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._type_next)

    # --- Controls other code can use ------------------------------------

    def log(self, message: str, source: str = "EVE") -> None:
        """Add a line. It's typed out after any lines already waiting."""
        self._waiting.append(f"[{source}] {message}")
        if not self._timer.isActive() and not self._typing:
            self._start_next_line()

    def clear(self) -> None:
        """Wipe the feed and forget anything waiting."""
        self._timer.stop()
        self._lines.clear()
        self._waiting.clear()
        self._typing = ""
        self._shown = 0
        self.text_changed.emit("")

    # --- Typing ---------------------------------------------------------

    def _start_next_line(self) -> None:
        if not self._waiting:
            self.queue_empty.emit()
            return
        self._typing = self._waiting.popleft()
        self._shown = 0
        self._type_next()

    def _type_next(self) -> None:
        if not self._typing:
            self._start_next_line()
            return
        # Behind? Show the whole line at once instead of typing it.
        if len(self._waiting) >= CATCH_UP_AT:
            self._shown = len(self._typing)
        else:
            self._shown += 1
        self._emit()

        if self._shown < len(self._typing):
            self._timer.start(TYPE_SPEED_MS)
        else:
            self._lines.append(self._typing)   # line finished: move it into the list
            self._typing = ""
            self._emit()
            self._timer.start(LINE_PAUSE_MS)   # then _type_next starts the next line

    def _emit(self) -> None:
        lines = list(self._lines)
        if self._typing:
            lines.append(self._typing[: self._shown] + "_")   # "_" is the typing cursor
            lines = lines[-MAX_LINES:]
        self.text_changed.emit("\n".join(lines))


if __name__ == "__main__":
    # Quick self-test: run  .venv\Scripts\python -m ui.event_log
    import sys
    from PySide6.QtCore import QCoreApplication

    app = QCoreApplication(sys.argv)
    feed = EventLog()
    for i in range(1, 8):
        feed.log(f"Test line {i}")
    feed.queue_empty.connect(lambda: (print("Last 5 lines on screen:"), print(final["text"]), app.quit()))
    final = {"text": ""}
    feed.text_changed.connect(lambda t: final.update(text=t))
    app.exec()
