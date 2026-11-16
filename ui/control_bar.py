"""
The row of on-screen buttons along the bottom of the HUD.

    [ TALK ]  [ MIC: ON ]  [ TYPE ]  [ MODE: FAST ]  [ WAKE: ON ]  [ LOG ]  [ POWER ]

Each button sends the same signal as its keyboard shortcut, so the rest
of E.V.E. doesn't know (or care) whether you clicked or pressed a key.
The keys still work: Space, N, /, M, W, L, Esc.
MIC turns red (MIC: OFF) while the microphone is muted.

When the HUD is made narrow, the buttons switch to short labels
(set_compact), so they still fit:

    [ 🎙 ]  [ 🎤 ]  [ ⌨ ]  [ FAST ]  [ 👂 ON ]  [ ☰ ]  [ ⏻ ]

This file only draws the buttons and reports clicks. hud_window.py
connects them up.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from ui import theme
from ui.eye_state import EyeState

# The colour TALK lights up in while held: the same as the eye's LISTENING colour.
LISTEN_COLOUR = theme.STATE_STYLE[EyeState.LISTENING][1]


def _style(accent: QColor, hover_bg: QColor) -> str:
    """The look of one button (Qt stylesheets work like CSS)."""
    return f"""
        QPushButton {{
            color: {accent.name()};
            background: transparent;
            border: 1px solid {theme.CYAN_DIM.name(QColor.HexArgb)};
            border-radius: 8px;
            padding: 6px 14px;
        }}
        QPushButton:hover {{
            color: white;
            border-color: {accent.name()};
            background: {theme.CYAN_GLOW.name(QColor.HexArgb)};
        }}
        QPushButton:pressed, QPushButton:checked {{
            color: {theme.BACKGROUND.name()};
            background: {hover_bg.name()};
            border-color: {hover_bg.name()};
        }}
        QPushButton:disabled {{
            color: {theme.TEXT_DIM.name()};
            border-color: {theme.CYAN_GLOW.name(QColor.HexArgb)};
        }}
    """


class ControlBar(QWidget):
    talk_pressed = Signal()    # TALK held down
    talk_released = Signal()   # TALK let go
    mic_clicked = Signal()
    type_clicked = Signal()
    mode_clicked = Signal()
    wake_clicked = Signal()
    log_clicked = Signal()
    power_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")

        self.talk = self._button("🎙  TALK", "Hold to talk to E.V.E. (or hold Space)", LISTEN_COLOUR)
        self.mic = self._button("🎤  MIC: ON", "Mute or unmute the microphone (or press N). "
                                "Muted = she can't hear anything, not even her name")
        self.type = self._button("⌨  TYPE", "Type to E.V.E. (or press /)")
        self.mode = self._button("MODE: —", "Switch between fast and think mode (or press M)")
        self.wake = self._button("WAKE: —", 'Listen for "Eve" on or off (or press W)')
        self.log = self._button("☰  LOG", "Show the last 10 chats (or press L)")
        self.log.setCheckable(True)   # stays lit while the chat log is open
        self.power = self._button("⏻  POWER", "Shut E.V.E. down (or press Esc)", theme.DANGER)

        # TALK works like a walkie-talkie: down = start, up = send.
        # (pressed/released, not clicked, so holding it down works.)
        self.talk.pressed.connect(self.talk_pressed)
        self.talk.released.connect(self.talk_released)
        self.mic.clicked.connect(self.mic_clicked)
        self.type.clicked.connect(self.type_clicked)
        self.mode.clicked.connect(self.mode_clicked)
        self.wake.clicked.connect(self.wake_clicked)
        self.log.clicked.connect(self.log_clicked)
        self.power.clicked.connect(self.power_clicked)

        # MODE and WAKE are greyed out until the voice says what they are.
        self.mode.setEnabled(False)
        self.wake.setEnabled(False)
        self._compact = False
        self._mode_word = "—"   # "FAST" / "THINK"
        self._wake_word = "—"   # "ON" / "OFF"
        self._muted = False

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 6, 0, 0)
        row.setSpacing(10)
        row.addStretch()
        for button in self._buttons():
            row.addWidget(button)
        row.addStretch()

    @staticmethod
    def _button(text: str, tip: str, accent: QColor = theme.CYAN) -> QPushButton:
        button = QPushButton(text)
        button.setFont(theme.font(11, bold=True))
        button.setCursor(Qt.PointingHandCursor)
        button.setToolTip(tip)
        # Clicking a button mustn't steal the keyboard, or Space / M etc. stop working.
        button.setFocusPolicy(Qt.NoFocus)
        button.setStyleSheet(_style(accent, accent))
        return button

    def _buttons(self) -> tuple:
        return (self.talk, self.mic, self.type, self.mode, self.wake, self.log, self.power)

    # --- Updating the labels (called by the window) ---------------------

    def show_mode(self, mode: str) -> None:
        """e.g. "FAST" -> the button reads MODE: FAST."""
        self._mode_word = mode
        self.mode.setEnabled(True)
        self._label()

    def show_wake(self, on: bool) -> None:
        self._wake_word = "ON" if on else "OFF"
        self.wake.setEnabled(True)
        self._label()

    def show_muted(self, muted: bool) -> None:
        """MIC: OFF in red while muted; MIC: ON in cyan otherwise."""
        self._muted = muted
        self.mic.setStyleSheet(_style(theme.DANGER, theme.DANGER) if muted else _style(theme.CYAN, theme.CYAN))
        self._label()

    def set_compact(self, compact: bool) -> None:
        """Short labels (True) for a narrow HUD, or the full ones (False)."""
        if compact != self._compact:
            self._compact = compact
            self._label()

    def _label(self) -> None:
        """Write each button's text, short or full."""
        if self._compact:
            texts = ["🎙", "🔇" if self._muted else "🎤", "⌨", self._mode_word, f"👂 {self._wake_word}", "☰", "⏻"]
        else:
            texts = ["🎙  TALK", "🔇  MIC: OFF" if self._muted else "🎤  MIC: ON", "⌨  TYPE", f"MODE: {self._mode_word}", f"WAKE: {self._wake_word}", "☰  LOG", "⏻  POWER"]
        for button, text in zip(self._buttons(), texts):
            button.setText(text)

    def width_needed(self, compact: bool) -> int:
        """
        How wide the row of buttons needs to be with short or full labels.
        Measured with the LONGEST words ("THINK", "OFF"), so the answer never
        changes when the mode does and the HUD doesn't jump between layouts.
        """
        was = (self._compact, self._mode_word, self._wake_word, self._muted)
        self._compact, self._mode_word, self._wake_word, self._muted = compact, "THINK", "OFF", True
        self._label()
        width = self.minimumSizeHint().width()
        self._compact, self._mode_word, self._wake_word, self._muted = was
        self._label()
        return width
