"""
The TIMERS panel, bottom-left of the HUD: a countdown for each running timer.

It looks like the side panels (it's built on the same Panel). Four times a
second it asks the timer keeper (actions/timers.py) what's running and
redraws. When nothing is running it hides itself.

Each row shows the label, the time left, and a thin bar that fills up as the
time runs out, turning amber near the end (the same Bar as CPU and RAM).

The panel only SHOWS timers. Setting, cancelling and going off all happen
in the timer keeper, so they still work with the HUD closed.
"""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QHBoxLayout

from ui import theme
from ui.side_panel import Bar, Panel, make_label

MAX_ROWS = 4          # more than this and the panel says "+2 more"
WARN_SECONDS = 10     # the time turns amber in the last 10 seconds


def countdown(seconds: float) -> str:
    """483 -> '08:03', 5400 -> '1:30:00'. Rounded up, so it never shows 00:00 early."""
    seconds = int(seconds + 0.999)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02}:{secs:02}" if hours else f"{minutes:02}:{secs:02}"


class TimerRow:
    """One timer's label, time and bar."""

    def __init__(self, panel: Panel):
        self.name = make_label(12, theme.TEXT)
        self.time = make_label(16, theme.CYAN, bold=True)
        self.bar = Bar()
        self.bar.setFixedHeight(6)
        top = QHBoxLayout()
        top.addWidget(self.name)
        top.addStretch()
        top.addWidget(self.time)
        panel.body.addLayout(top)
        panel.body.addWidget(self.bar)
        self.widgets = (self.name, self.time, self.bar)

    def show(self, timer) -> None:
        left = timer.seconds_left()
        self.name.setText((timer.label or f"timer {timer.number}").upper())
        self.time.setText(countdown(left))
        colour = theme.WARNING if left <= WARN_SECONDS else theme.CYAN
        self.time.setStyleSheet(f"color: {colour.name()}; background: transparent;")
        self.bar.set_percent(100 * (1 - left / timer.seconds))
        self.set_visible(True)

    def set_visible(self, visible: bool) -> None:
        for widget in self.widgets:
            widget.setVisible(visible)


class TimerPanel(Panel):
    def __init__(self, keeper, parent=None):
        """`keeper` is the timer keeper; all the panel needs is its running()."""
        super().__init__("TIMERS", parent)
        self.keeper = keeper
        self.setMinimumHeight(0)   # only as tall as its timers (side panels are taller)
        self.rows = [TimerRow(self) for _ in range(MAX_ROWS)]
        self.more = make_label(11, theme.TEXT_DIM)
        self.body.addWidget(self.more)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(250)
        self.refresh()

    def refresh(self) -> None:
        timers = self.keeper.running()
        self.setVisible(bool(timers))
        for row, timer in zip(self.rows, timers):
            row.show(timer)
        for row in self.rows[len(timers):]:
            row.set_visible(False)
        extra = len(timers) - MAX_ROWS
        self.more.setText(f"+{extra} more" if extra > 0 else "")
        self.more.setVisible(extra > 0)


if __name__ == "__main__":
    # Visual test: run  .venv\Scripts\python -m ui.timer_panel
    # Shows a few timers counting down; the 12-second one goes amber and vanishes.
    import sys
    from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout

    from actions.timers import get_timers

    app = QApplication(sys.argv)
    keeper = get_timers()
    keeper.add(12, "tea")
    keeper.add(8 * 60, "pasta")
    keeper.add(90 * 60)
    window = QWidget()
    window.setWindowTitle("E.V.E. timer panel test")
    window.setStyleSheet(f"background-color: {theme.BACKGROUND.name()};")
    QVBoxLayout(window).addWidget(TimerPanel(keeper))
    window.show()
    sys.exit(app.exec())
