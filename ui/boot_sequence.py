"""
E.V.E.'s startup: writes the boot lines and opens the eye.

This is a "director": it draws nothing. It tells the animator to replay
the twist-open, sends the boot lines to the event log (which types them
out), and once the last line is typed switches the eye to IDLE. After
that the same log keeps going as E.V.E.'s live feed.
"""

from PySide6.QtCore import QObject, QTimer, Signal

from ui.event_log import EventLog
from ui.eye_animator import EyeAnimator
from ui.eye_state import EyeState

BOOT_LINES = [
    "INITIALISING E.V.E...",
    "LOADING CORE MODULES... OK",
    "CALIBRATING OPTICS... OK",
    "SYSTEMS ONLINE",
]


class BootSequence(QObject):
    finished = Signal()   # the boot is complete

    def __init__(self, animator: EyeAnimator, event_log: EventLog, parent=None):
        super().__init__(parent)
        self.animator = animator
        self.event_log = event_log
        self.running = False
        # If True, the eye stays in BOOTING after the text finishes, and
        # whoever set this (main.py, waiting for the voice) switches it to IDLE.
        self.wait_for_ready = False
        # When the log has typed everything, the boot is over.
        event_log.queue_empty.connect(self._on_log_done)

    def start(self) -> None:
        """Begin (or restart) the boot."""
        self.running = True
        self.event_log.clear()
        self.animator.restart_boot()   # rings snap closed and start twisting open
        # A short pause before the first line, so the rings get going first.
        QTimer.singleShot(400, self._write_lines)

    def _write_lines(self) -> None:
        for line in BOOT_LINES:
            self.event_log.log(line, source="BOOT")

    def _on_log_done(self) -> None:
        if self.running:
            self.running = False
            if not self.wait_for_ready:
                self.animator.set_state(EyeState.IDLE)
            self.finished.emit()


SHUTDOWN_LINES = [
    "SHUTTING DOWN...",
    "SAVING STATE... OK",
    "GOODBYE",
]


class ShutdownSequence(QObject):
    """The boot in reverse: rings twist closed, glow fades, goodbye lines typed."""

    finished = Signal()   # safe to close the window now

    def __init__(self, animator: EyeAnimator, event_log: EventLog, parent=None):
        super().__init__(parent)
        self.animator = animator
        self.event_log = event_log
        self.running = False
        event_log.queue_empty.connect(self._on_log_done)

    def start(self) -> None:
        if self.running:
            return   # already shutting down; ignore extra clicks
        self.running = True
        self.animator.set_state(EyeState.SHUTDOWN)
        for line in SHUTDOWN_LINES:
            self.event_log.log(line, source="SYS")

    def _on_log_done(self) -> None:
        if self.running:
            # Give the rings a moment to finish closing before we say "done".
            QTimer.singleShot(300, self.finished.emit)


if __name__ == "__main__":
    # Quick self-test with no window: run  .venv\Scripts\python -m ui.boot_sequence
    import sys
    from PySide6.QtCore import QCoreApplication

    app = QCoreApplication(sys.argv)
    animator = EyeAnimator()
    log = EventLog()
    boot = BootSequence(animator, log)
    text = {"now": ""}
    log.text_changed.connect(lambda t: text.update(now=t))

    def done():
        print(text["now"])
        print(f"\n[boot finished, eye is now {animator.state.name}]")
        QTimer.singleShot(100, app.quit)

    boot.finished.connect(done)
    boot.start()
    app.exec()
