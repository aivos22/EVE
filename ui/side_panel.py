"""
The side panels: a clock/date panel and a CPU/RAM panel.

Each panel has its own one-second timer and refreshes itself, so the
window just places them and forgets about them. CPU and RAM numbers
come from psutil, a library that reads your computer's live stats.
"""

from datetime import datetime

import psutil
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ui import theme

WARN_AT = 85  # percent: bars turn amber above this


def make_label(size: int, color, bold: bool = False) -> QLabel:
    """A transparent text label in E.V.E.'s font."""
    label = QLabel()
    label.setFont(theme.font(size, bold))
    label.setStyleSheet(f"color: {color.name()}; background: transparent;")
    return label


class Panel(QWidget):
    """A see-through card with a cyan border and a small title. Others build on this."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setFixedWidth(theme.PANEL_WIDTH)
        self.body = QVBoxLayout(self)
        self.setMinimumHeight(230)
        self.body.setContentsMargins(22, 18, 22, 22)
        self.body.setSpacing(8)
        header = make_label(11, theme.CYAN, bold=True)
        header.setText(f"// {title}")
        self.body.addWidget(header)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        box = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setBrush(theme.PANEL_BG)
        p.setPen(QPen(theme.CYAN_DIM, 1))
        p.drawRoundedRect(box, 10, 10)
        # A short bright accent line along the top edge, for the HUD look.
        p.setPen(QPen(theme.CYAN, 2))
        p.drawLine(int(box.left()) + 14, int(box.top()), int(box.left()) + 60, int(box.top()))
        p.end()


class Bar(QWidget):
    """A thin horizontal meter that fills from 0 to 100 percent."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.percent = 0.0
        self.setFixedHeight(12)

    def set_percent(self, value: float) -> None:
        self.percent = value
        self.update()  # ask Qt to repaint the bar

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        full = QRectF(self.rect())
        p.setPen(Qt.NoPen)
        p.setBrush(theme.CYAN_GLOW)
        p.drawRoundedRect(full, 3, 3)
        filled = QRectF(full.x(), full.y(), full.width() * self.percent / 100, full.height())
        p.setBrush(theme.WARNING if self.percent >= WARN_AT else theme.CYAN)
        p.drawRoundedRect(filled, 3, 3)
        p.end()


class ClockPanel(Panel):
    """Time and date, updated every second."""

    def __init__(self, parent=None):
        super().__init__("CHRONO", parent)
        self.time_label = make_label(34, theme.TEXT, bold=True)
        self.seconds_label = make_label(12, theme.TEXT_DIM)
        self.date_label = make_label(14, theme.CYAN)
        self.body.addWidget(self.time_label)
        self.body.addWidget(self.seconds_label)
        self.body.addSpacing(6)
        self.body.addWidget(self.date_label)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(1000)
        self.refresh()

    def refresh(self) -> None:
        now = datetime.now()
        self.time_label.setText(now.strftime("%H:%M"))
        self.seconds_label.setText(now.strftime("SEC %S"))
        self.date_label.setText(now.strftime("%a %d %b %Y").upper())


class SystemPanel(Panel):
    """CPU and RAM use, with a bar for each, updated every second."""

    def __init__(self, parent=None):
        super().__init__("SYSTEM", parent)
        self.cpu_label = make_label(14, theme.TEXT)
        self.cpu_bar = Bar()
        self.cpu_detail = make_label(11, theme.TEXT_DIM)
        self.ram_label = make_label(14, theme.TEXT)
        self.ram_bar = Bar()
        self.ram_detail = make_label(11, theme.TEXT_DIM)

        self.body.addWidget(self.cpu_label)
        self.body.addWidget(self.cpu_bar)
        self.body.addWidget(self.cpu_detail)
        self.body.addSpacing(10)
        self.body.addWidget(self.ram_label)
        self.body.addWidget(self.ram_bar)
        self.body.addWidget(self.ram_detail)

        # psutil measures CPU *between* calls, so the very first reading is
        # meaningless. Call it once now to start the measuring.
        psutil.cpu_percent(interval=None)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(1000)
        self.refresh()

    def refresh(self) -> None:
        cpu = psutil.cpu_percent(interval=None)   # percent since last call, no waiting
        ram = psutil.virtual_memory()             # total, used, percent...
        self.cpu_label.setText(f"CPU   {cpu:5.1f}%")
        self.cpu_bar.set_percent(cpu)
        self.cpu_detail.setText(f"{psutil.cpu_count()} CORES")
        self.ram_label.setText(f"RAM   {ram.percent:5.1f}%")
        self.ram_bar.set_percent(ram.percent)
        gb = 1024 ** 3
        self.ram_detail.setText(f"{ram.used / gb:.1f} / {ram.total / gb:.1f} GB")


if __name__ == "__main__":
    # Visual test: run  .venv\Scripts\python -m ui.side_panel
    import sys
    from PySide6.QtWidgets import QApplication, QHBoxLayout

    app = QApplication(sys.argv)
    window = QWidget()
    window.setWindowTitle("E.V.E. side panels test")
    window.setStyleSheet(f"background-color: {theme.BACKGROUND.name()};")
    row = QHBoxLayout(window)
    row.addWidget(ClockPanel())
    row.addWidget(SystemPanel())
    window.show()
    sys.exit(app.exec())
