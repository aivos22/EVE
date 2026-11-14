"""
E.V.E.'s main window: frameless, dark, see-through, with cyan edges.

This file only handles the WINDOW: its look, its layout, moving it
around and the temporary test keys. The eye's behaviour lives in
EyeAnimator, which is passed in, so other code (voice, AI) can hold
the same animator and change the eye's state.
"""

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ui import theme
from ui.eye_animator import EyeAnimator
from ui.eye_state import STATE_KEYS, EyeState
from ui.eye_widget import EyeWidget


class HudWindow(QWidget):
    def __init__(self, animator: EyeAnimator | None = None):
        super().__init__()
        # Use the animator we were given, or make our own for testing.
        self.animator = animator or EyeAnimator(self)
        self._drag_offset: QPoint | None = None

        self._setup_window()
        self._build_layout()
        self.animator.state_changed.connect(self._show_state)
        self._show_state(self.animator.state)

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
        # Placeholders for the side panels; step 6 fills these in.
        self.left_panel = QWidget()
        self.left_panel.setFixedWidth(theme.PANEL_WIDTH)
        self.right_panel = QWidget()
        self.right_panel.setFixedWidth(theme.PANEL_WIDTH)

        self.eye = EyeWidget(self.animator)

        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setFont(theme.font(12, bold=True))
        self.status_label.setStyleSheet(f"color: {theme.CYAN.name()}; background: transparent;")

        centre = QVBoxLayout()
        centre.addWidget(self.eye, stretch=1)
        centre.addWidget(self.status_label)

        row = QHBoxLayout(self)
        row.setContentsMargins(24, 24, 24, 24)
        row.setSpacing(16)
        row.addWidget(self.left_panel)
        row.addLayout(centre, stretch=1)
        row.addWidget(self.right_panel)

    def _show_state(self, state: EyeState) -> None:
        self.status_label.setText(f"STATUS // {state.name}")

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
            self.animator.restart_boot()
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
