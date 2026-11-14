"""
E.V.E.'s startup: types out the boot text and opens the eye.

This is a "director": it doesn't draw anything. It tells the animator
to replay the twist-open, types the text one letter at a time, and
when it's done switches the eye to IDLE. Whoever wants to show the
text (the HUD window) listens to the `text_changed` signal.
"""

from PySide6.QtCore import QObject, QTimer, Signal

from ui.eye_animator import EyeAnimator
from ui.eye_state import EyeState

BOOT_LINES = [
    "INITIALISING E.V.E...",
    "LOADING CORE MODULES... OK",
    "CALIBRATING OPTICS... OK",
    "SYSTEMS ONLINE",
]
TYPE_SPEED_MS = 35      # time between letters
LINE_PAUSE_MS = 350     # pause at the end of each line
CLEAR_AFTER_MS = 2500   # how long the finished text stays before clearing


class BootSequence(QObject):
    text_changed = Signal(str)   # the full text typed so far
    finished = Signal()          # the boot is complete

    def __init__(self, animator: EyeAnimator, parent=None):
        super().__init__(parent)
        self.animator = animator
        self._line = 0       # which line we're typing
        self._char = 0       # how many letters of that line are shown
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)   # fire once, we re-arm it each time
        self._timer.timeout.connect(self._type_next)

    def start(self) -> None:
        """Begin (or restart) the boot from the first letter."""
        self._line = 0
        self._char = 0
        self.animator.restart_boot()      # rings snap closed and start twisting open
        self.text_changed.emit("")
        self._timer.start(400)            # short pause before the first letter

    def _type_next(self) -> None:
        line = BOOT_LINES[self._line]
        self._char += 1
        self.text_changed.emit(self._current_text())

        if self._char < len(line):
            self._timer.start(TYPE_SPEED_MS)       # next letter on this line
        elif self._line < len(BOOT_LINES) - 1:
            self._line += 1                         # move to the next line
            self._char = 0
            self._timer.start(LINE_PAUSE_MS)
        else:
            self._finish()

    def _current_text(self) -> str:
        done = BOOT_LINES[: self._line]                       # whole lines already typed
        partial = BOOT_LINES[self._line][: self._char]        # the line being typed
        cursor = "_" if self._char < len(BOOT_LINES[self._line]) else ""
        return "\n".join(["> " + l for l in done] + ["> " + partial + cursor])

    def _finish(self) -> None:
        self.animator.set_state(EyeState.IDLE)
        self.finished.emit()
        # Clear the text a little later (unless the boot was restarted meanwhile).
        QTimer.singleShot(CLEAR_AFTER_MS, self._clear_if_done)

    def _clear_if_done(self) -> None:
        if not self._timer.isActive() and self.animator.state != EyeState.BOOTING:
            self.text_changed.emit("")


if __name__ == "__main__":
    # Quick self-test with no window: run  .venv\Scripts\python -m ui.boot_sequence
    import sys
    from PySide6.QtCore import QCoreApplication

    app = QCoreApplication(sys.argv)
    animator = EyeAnimator()
    boot = BootSequence(animator)
    boot.finished.connect(lambda: print(f"\n[boot finished, eye is now {animator.state.name}]"))
    boot.finished.connect(lambda: QTimer.singleShot(200, app.quit))

    last = {"lines": 0}

    def show(text: str):
        # Print each line once it's fully typed, so the terminal isn't flooded.
        lines = text.split("\n")
        complete = [l for l in lines if not l.endswith("_")]
        for l in complete[last["lines"]:]:
            if l.strip() not in ("", ">"):
                print(l)
        last["lines"] = len(complete)

    boot.text_changed.connect(show)
    boot.start()
    app.exec()
