"""
E.V.E.'s main window: frameless, dark, see-through, with cyan edges.

This file only handles the WINDOW: its look, its layout, moving it
around and the temporary test keys. The eye's behaviour lives in
EyeAnimator, which is passed in, so other code (voice, AI) can hold
the same animator and change the eye's state.
"""

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ui import theme
from ui.boot_sequence import BootSequence
from ui.eye_animator import EyeAnimator
from ui.eye_state import STATE_KEYS, EyeState
from ui.eye_widget import EyeWidget
from ui.side_panel import ClockPanel, SystemPanel


class HudWindow(QWidget):
    def __init__(self, animator: EyeAnimator | None = None):
        super().__init__()
        # Use the animator we were given, or make our own for testing.
        self.animator = animator or EyeAnimator(self)
        self._drag_offset: QPoint | None = None
        self._booted = False
        self.boot = BootSequence(self.animator, self)

        self._setup_window()
        self._build_layout()
        self.animator.state_changed.connect(self._show_state)
        self._show_state(self.animator.state)
        self.boot.text_changed.connect(self.boot_label.setText)

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

        # Where the boot text gets typed. Fixed height so nothing jumps when it clears.
        self.boot_label = QLabel()
        self.boot_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.boot_label.setFont(theme.font(11))
        self.boot_label.setFixedHeight(80)
        self.boot_label.setStyleSheet(f"color: {theme.TEXT.name()}; background: transparent;")

        centre = QVBoxLayout()
        centre.addWidget(self.eye, stretch=1)
        centre.addWidget(self.boot_label)
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
        title = QLabel("E.V.E")
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
        # When clicked, close the window. Closing the last window ends the program.
        close_button.clicked.connect(self.close)

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
        self.status_label.setText(f"STATUS // {state.name}")

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
        key = event.text().lower()
        if key in STATE_KEYS:
            self.animator.set_state(STATE_KEYS[key])
        elif key == "b":
            self.boot.start()  # replay the whole startup, text and all
        elif event.key() == Qt.Key_Escape:
            self.close()

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
