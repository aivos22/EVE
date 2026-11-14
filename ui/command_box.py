"""
The typed command bar: for when you can't talk out loud.

Press / in the HUD and a text box appears under the eye. Type a message,
press Enter to send it to E.V.E., or Esc to close the box without sending.

This only handles the box itself. The window decides when to open it, and
whatever the message is sent to (the voice controller) decides what to do.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLineEdit, QSizePolicy

from ui import theme

MAX_LENGTH = 500   # characters; plenty for a question


class CommandBox(QLineEdit):
    submitted = Signal(str)   # the message you typed, sent when you press Enter
    closed = Signal()         # the box has closed (sent or not)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setPlaceholderText("Type to E.V.E.  ·  Enter to send  ·  Esc to cancel")
        self.setMaxLength(MAX_LENGTH)
        self.setFont(theme.font(12))
        self.setFixedHeight(34)
        self.setStyleSheet(f"""
            QLineEdit {{
                color: {theme.TEXT.name()};
                background: {theme.PANEL_BG.name(QColor.HexArgb)};
                border: 1px solid {theme.CYAN.name()};
                border-radius: 6px;
                padding: 0 10px;
                selection-background-color: {theme.CYAN_DIM.name(QColor.HexArgb)};
            }}
        """)
        # Keep its space in the layout even while hidden, so the eye and
        # captions don't jump up and down when the box opens and closes.
        policy = self.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.setSizePolicy(policy)
        self.returnPressed.connect(self._send)
        self.hide()

    def open(self) -> None:
        """Show the box, ready to type into."""
        self.clear()
        self.show()
        self.setFocus()   # key presses now go to the box, not the window

    def close_box(self) -> None:
        self.hide()
        self.clear()
        self.closed.emit()

    def _send(self) -> None:
        text = self.text().strip()
        self.close_box()
        if text:
            self.submitted.emit(text)

    def keyPressEvent(self, event):
        # Esc closes the box. (Without this, Esc would reach the window
        # and start the shutdown!)
        if event.key() == Qt.Key_Escape:
            self.close_box()
            return
        super().keyPressEvent(event)
