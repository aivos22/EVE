"""
E.V.E.'s main window: frameless, dark, see-through, with cyan edges.

This file only handles the WINDOW: its look, its layout, moving it
around and the temporary test keys. The eye's behaviour lives in
EyeAnimator and the log lines in EventLog. Both are passed in, so other
code (voice, AI) can hold the same objects and drive the HUD.
"""

from PySide6.QtCore import QPoint, QPropertyAnimation, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ui import theme
from ui.boot_sequence import BootSequence, ShutdownSequence
from ui.event_log import EventLog
from ui.eye_animator import EyeAnimator
from ui.eye_state import STATE_KEYS, EyeState
from ui.eye_widget import EyeWidget
from ui.side_panel import ClockPanel, SystemPanel

# What the log feed says when E.V.E. enters each state.
STATE_MESSAGES = {
    EyeState.IDLE: "Standing by",
    EyeState.LISTENING: "Listening...",
    EyeState.THINKING: "Processing request...",
    EyeState.SPEAKING: "Responding",
    EyeState.LOOKING: "Scanning surroundings",
}


class HudWindow(QWidget):
    def __init__(self, animator: EyeAnimator | None = None, event_log: EventLog | None = None):
        super().__init__()
        # Use the animator and log we were given, or make our own for testing.
        self.animator = animator or EyeAnimator(self)
        self.event_log = event_log or EventLog(self)
        self._drag_offset: QPoint | None = None
        self._booted = False
        self.boot = BootSequence(self.animator, self.event_log, self)
        self.shutdown_sequence = ShutdownSequence(self.animator, self.event_log, self)
        self.shutdown_sequence.finished.connect(self._fade_out)

        self._setup_window()
        self._build_layout()
        self.animator.state_changed.connect(self._show_state)
        self._show_state(self.animator.state)
        self.event_log.text_changed.connect(self.log_label.setText)
        self.animator.state_changed.connect(self._log_state)

        # Mouse-follow: 30 times a second, tell the animator where the mouse is.
        self._gaze_timer = QTimer(self)
        self._gaze_timer.timeout.connect(self._follow_mouse)
        self._gaze_timer.start(33)

    # --- Window setup -----------------------------------------------------

    def _setup_window(self) -> None:
        self.setWindowTitle("E.V.E.")
        # Frameless = no Windows title bar or borders. StaysOnTop = floats above other apps.
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        # Let the desktop show through wherever we don't paint.
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(theme.WINDOW_WIDTH, theme.WINDOW_HEIGHT)

    def _build_layout(self) -> None:
        """Three columns: left panel | eye | right panel."""
        # Side panels: clock on the left, system stats on the right.
        self.clock_panel = ClockPanel()
        self.system_panel = SystemPanel()

        self.eye = EyeWidget(self.animator)

        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setFont(theme.font(12, bold=True))
        self.status_label.setStyleSheet(f"color: {theme.CYAN.name()}; background: transparent;")

        # The log feed: boot lines first, then E.V.E.'s live activity.
        # Fixed height (5 lines) so nothing jumps around as lines come and go.
        self.log_label = QLabel()
        self.log_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.log_label.setFont(theme.font(11))
        self.log_label.setFixedHeight(105)
        self.log_label.setStyleSheet(f"color: {theme.TEXT.name()}; background: transparent;")

        centre = QVBoxLayout()
        centre.addWidget(self.eye, stretch=1)
        centre.addWidget(self.log_label)
        centre.addWidget(self.status_label)

        row = QHBoxLayout()
        row.setSpacing(16)
        row.addLayout(self._column(self.clock_panel))
        row.addLayout(centre, stretch=1)
        row.addLayout(self._column(self.system_panel))

        # The whole window: top bar first, then the three columns below it.
        page = QVBoxLayout(self)
        page.setContentsMargins(24, 16, 24, 24)
        page.addLayout(self._build_top_bar())
        page.addLayout(row, stretch=1)

    def _build_top_bar(self) -> QHBoxLayout:
        """'E.V.E' on the left, a close (X) button on the right."""
        title = QLabel("E.V.E.")
        title.setFont(theme.font(16, bold=True))
        title.setStyleSheet(f"color: {theme.CYAN.name()}; background: transparent;")

        close_button = QPushButton("X")
        close_button.setFixedSize(32, 32)
        close_button.setFont(theme.font(12, bold=True))
        close_button.setCursor(Qt.PointingHandCursor)
        close_button.setToolTip("Quit E.V.E.")
        close_button.setFocusPolicy(Qt.NoFocus)  # so key presses still reach the window
        # A stylesheet is like CSS for Qt: how the button looks normally and on hover.
        close_button.setStyleSheet(f"""
            QPushButton {{
                color: {theme.CYAN.name()};
                background: transparent;
                border: 1px solid {theme.CYAN_DIM.name(QColor.HexArgb)};
                border-radius: 6px;
            }}
            QPushButton:hover {{
                color: white;
                background: {theme.DANGER.name()};
                border-color: {theme.DANGER.name()};
            }}
        """)
        # When clicked, play the shutdown animation, which then closes the window.
        close_button.clicked.connect(self.shutdown)

        bar = QHBoxLayout()
        bar.addWidget(title)
        bar.addStretch()  # pushes the button all the way to the right
        bar.addWidget(close_button)
        return bar

    @staticmethod
    def _column(panel: QWidget) -> QVBoxLayout:
        """Put a panel in a column with empty space above and below, so it sits in the middle."""
        col = QVBoxLayout()
        col.addStretch()
        col.addWidget(panel)
        col.addStretch()
        return col

    def _show_state(self, state: EyeState) -> None:
        word, colour = theme.STATE_STYLE[state]
        # Rich text (a tiny bit of HTML) lets one label use two colours.
        self.status_label.setText(
            f'<span style="color:{theme.TEXT_DIM.name()}">STATUS //</span> '
            f'<span style="color:{colour.name()}">{word}</span>')

    def shutdown(self) -> None:
        """Play the shutdown animation, then fade out and quit."""
        self.boot.running = False   # in case we're shut down mid-boot
        self.shutdown_sequence.start()

    def _fade_out(self) -> None:
        # QPropertyAnimation smoothly changes a property over time:
        # here the whole window's opacity, from fully visible to invisible.
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(400)
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self.close)   # closing the last window ends the program
        self._fade.start()

    def _follow_mouse(self) -> None:
        """Turn the mouse position into a -1..1 'look' direction for the eye."""
        eye_centre = self.eye.mapToGlobal(self.eye.rect().center())
        offset = QCursor.pos() - eye_centre
        reach = 600  # pixels from the eye at which it's looking fully sideways
        self.animator.set_gaze(offset.x() / reach, offset.y() / reach)

    def _log_state(self, state: EyeState) -> None:
        """Write a line in the feed whenever the state changes (not during boot)."""
        if state in STATE_MESSAGES and not self.boot.running:
            self.event_log.log(STATE_MESSAGES[state])

    def showEvent(self, event):
        # Play the boot sequence the first time the window appears.
        super().showEvent(event)
        if not self._booted:
            self._booted = True
            self.boot.start()

    # --- Drawing the window background ----------------------------------

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        box = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setBrush(theme.BACKGROUND)
        p.setPen(QPen(theme.CYAN_DIM, 1.5))
        p.drawRoundedRect(box, theme.CORNER_RADIUS, theme.CORNER_RADIUS)
        p.end()

    # --- Keyboard: temporary test controls ------------------------------

    def keyPressEvent(self, event):
        if self.shutdown_sequence.running:
            return   # ignore keys once we're shutting down
        key = event.text().lower()
        if key in STATE_KEYS:
            self.animator.set_state(STATE_KEYS[key])
        elif key == "b":
            self.boot.start()  # replay the whole startup, text and all
        elif event.key() == Qt.Key_Escape:
            self.shutdown()

    # --- Mouse: drag anywhere to move the window ------------------------
    # With no title bar, we handle moving ourselves: remember where the
    # mouse grabbed the window, then follow the mouse until it's released.

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None


if __name__ == "__main__":
    # Visual test: run  .venv\Scripts\python -m ui.hud_window
    # Keys: 1-5 states, B replay startup, Esc quit. Drag to move.
    import sys
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    window = HudWindow()
    window.show()
    sys.exit(app.exec())
