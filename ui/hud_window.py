"""
E.V.E.'s main window: frameless, dark, see-through, with cyan edges.

This file only handles the WINDOW: its look, its layout, moving and
resizing it, hiding it, and the temporary test keys. The eye's behaviour
lives in EyeAnimator and the log lines in EventLog. Both are passed in, so
other code (voice, AI) can hold the same objects and drive the HUD.

Resize: drag any edge or corner. Move: drag anywhere else.
Hide: the - button or H. Hiding only hides the WINDOW: E.V.E. keeps
running (wake word, timers, speaking). Bring her back from the tray icon
or by saying "Eve, show yourself". Size and position are remembered
between runs (ui/window_memory.py).
"""

from html import escape

from PySide6.QtCore import QPoint, QPropertyAnimation, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

from ui import theme, window_memory
from ui.boot_sequence import BootSequence, ShutdownSequence
from brain.rate_count import get_rate_count
from ui.chat_log_panel import ChatLogPanel
from ui.command_box import CommandBox
from ui.control_bar import ControlBar
from ui.event_log import EventLog
from ui.eye_animator import EyeAnimator
from ui.eye_state import STATE_KEYS, EyeState
from ui.eye_widget import EyeWidget
from ui.side_panel import ClockPanel, SystemPanel
from ui.timer_panel import TimerPanel
from ui.typewriter import Typewriter

TEST_TIMER_SECONDS = 10   # the T key starts a timer this long
EDGE = 8                  # pixels from the border where dragging resizes instead of moving
MARGINS = 48              # the window's left + right margins (see _build_layout)
COLUMN_GAP = 16           # space between the three columns
SLACK = 20                # a little spare room

# Which mouse cursor to show over each edge or corner.
EDGE_CURSORS = {
    Qt.LeftEdge: Qt.SizeHorCursor, Qt.RightEdge: Qt.SizeHorCursor,
    Qt.TopEdge: Qt.SizeVerCursor, Qt.BottomEdge: Qt.SizeVerCursor,
    Qt.TopEdge | Qt.LeftEdge: Qt.SizeFDiagCursor, Qt.BottomEdge | Qt.RightEdge: Qt.SizeFDiagCursor,
    Qt.TopEdge | Qt.RightEdge: Qt.SizeBDiagCursor, Qt.BottomEdge | Qt.LeftEdge: Qt.SizeBDiagCursor,
}

# What the log feed says when E.V.E. enters each state.
STATE_MESSAGES = {
    EyeState.IDLE: "Standing by",
    EyeState.LISTENING: "Listening...",
    EyeState.THINKING: "Processing request...",
    EyeState.SPEAKING: "Responding",
    EyeState.LOOKING: "Scanning surroundings",
}


class HudWindow(QWidget):
    # Push-to-talk. The window only reports the key; voice code decides what to do.
    talk_pressed = Signal()
    talk_released = Signal()
    mode_toggle_pressed = Signal()   # M key: switch the brain between fast and think
    wake_toggle_pressed = Signal()   # W key: switch the wake word ("Eve") on or off
    mute_toggle_pressed = Signal()   # N key: mute / unmute the microphone
    text_submitted = Signal(str)     # a message typed in the command bar (/ key)
    visibility_changed = Signal(bool)   # True = on screen, False = hidden (she's still running)

    def __init__(self, animator: EyeAnimator | None = None, event_log: EventLog | None = None,
                 timers=None):
        super().__init__()
        # Use the animator and log we were given, or make our own for testing.
        self.animator = animator or EyeAnimator(self)
        self.event_log = event_log or EventLog(self)
        if timers is None:
            from actions.timers import get_timers
            timers = get_timers()
        self.timers = timers   # the timer keeper; the TIMERS panel shows what it holds
        self._drag_offset: QPoint | None = None
        self._edge_cursor = None   # the resize cursor showing now, if any
        self._booted = False
        # Saving the size on every pixel of a drag would be wasteful, so we
        # wait until the window has been still for half a second.
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(500)
        self._save_timer.timeout.connect(lambda: window_memory.save(self.geometry()))
        self._you_said = ""   # caption text
        self._eve_said = ""   # as much of her sentence as has been typed so far
        self._eve_rest = ""   # the part not typed yet (drawn invisibly, to hold its place)
        self._mode = ""       # the brain's mode, shown after the status, e.g. "FAST"
        self._wake = ""       # "ON" / "OFF" for the wake word, or "" before she's loaded
        self._muted = False   # microphone muted (N key / MIC button)
        self._gemini = ""     # e.g. "12/15 LEFT · 84 TODAY" (see _update_gemini_count)
        # Types her sentences out letter by letter (see ui/typewriter.py).
        self.typewriter = Typewriter(self)
        self.typewriter.text_changed.connect(self._on_typed)
        self.boot = BootSequence(self.animator, self.event_log, self)
        self.shutdown_sequence = ShutdownSequence(self.animator, self.event_log, self)
        self.shutdown_sequence.finished.connect(self._fade_out)

        self._setup_window()
        self._build_layout()
        self._compact = None          # True = narrow layout (see _fit_layout)
        self._timers_showing = False
        # Open where she was last time, or at the normal size if there's no saved spot.
        saved = window_memory.load()
        if saved:
            self.setGeometry(saved)
        else:
            self.resize(max(theme.WINDOW_WIDTH, self._full_width()), theme.WINDOW_HEIGHT)
        self._fit_layout()
        self.animator.state_changed.connect(self._show_state)
        self._show_state(self.animator.state)
        self.event_log.text_changed.connect(self.log_label.setText)

        # 30 times a second: tell the animator where the mouse is (the eye
        # follows it), and show a resize cursor when it's over an edge.
        self._gaze_timer = QTimer(self)
        self._gaze_timer.timeout.connect(self._follow_mouse)
        self._gaze_timer.timeout.connect(self._update_edge_cursor)
        self._gaze_timer.timeout.connect(self._check_timers_panel)
        # (The eye can also move when the command box opens, so the chat log
        # panel follows it here too, while it's open.)
        self._gaze_timer.timeout.connect(lambda: self.chat_log_panel.isVisible() and self._place_chat_log())
        self._gaze_timer.start(33)

        # Once a second: how many Gemini requests are left this minute.
        self.rate_count = get_rate_count()
        self._count_timer = QTimer(self)
        self._count_timer.timeout.connect(self._update_gemini_count)
        self._count_timer.start(1000)
        self._update_gemini_count()

    # --- Window setup -----------------------------------------------------

    def _setup_window(self) -> None:
        self.setWindowTitle("E.V.E.")
        # Frameless = no Windows title bar or borders. StaysOnTop = floats above other apps.
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        # Let the desktop show through wherever we don't paint.
        self.setAttribute(Qt.WA_TranslucentBackground)
        # (The size is set in __init__, once the layout exists to measure.)

    def _build_layout(self) -> None:
        """Three columns: left panel | eye | right panel."""
        # Side panels: clock on the left, system stats on the right.
        self.clock_panel = ClockPanel()
        self.system_panel = SystemPanel()
        self.timer_panel = TimerPanel(self.timers)   # hides itself when no timers run

        self.eye = EyeWidget(self.animator)

        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setFont(theme.font(12, bold=True))
        self.status_label.setStyleSheet(f"color: {theme.CYAN.name()}; background: transparent;")

        # Caption: what you said, then E.V.E.'s reply underneath.
        self.caption_label = QLabel()
        self.caption_label.setAlignment(Qt.AlignCenter)
        self.caption_label.setWordWrap(True)
        self.caption_label.setFont(theme.font(12))
        self.caption_label.setFixedHeight(56)
        self.caption_label.setStyleSheet("background: transparent;")

        # The typed command bar, hidden until you press /.
        self.command_box = CommandBox()
        self.command_box.submitted.connect(self.text_submitted)   # pass the message on
        self.command_box.closed.connect(self.setFocus)            # keys go back to the window

        # The log feed: boot lines first, then E.V.E.'s live activity.
        # Fixed height (5 lines) so nothing jumps around as lines come and go.
        self.log_label = QLabel()
        self.log_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.log_label.setFont(theme.font(11))
        self.log_label.setFixedHeight(105)
        self.log_label.setStyleSheet(f"color: {theme.TEXT.name()}; background: transparent;")
        # A label normally insists on being as wide as its longest line, which
        # would stop the window being made narrower (and a long log line could
        # even push it wider). "Ignored" lets long lines be cut off instead.
        for label in (self.log_label, self.status_label):
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        # The on-screen buttons. They send exactly the same signals as the keys.
        self.controls = ControlBar()
        self.controls.talk_pressed.connect(self.talk_pressed)
        self.controls.talk_released.connect(self.talk_released)
        self.controls.mic_clicked.connect(self.mute_toggle_pressed)
        self.controls.type_clicked.connect(self.command_box.open)
        self.controls.mode_clicked.connect(self.mode_toggle_pressed)
        self.controls.wake_clicked.connect(self.wake_toggle_pressed)
        self.controls.power_clicked.connect(self.shutdown)
        self.controls.log_clicked.connect(self.toggle_chat_log)

        centre = QVBoxLayout()
        centre.addWidget(self.eye, stretch=1)
        centre.addWidget(self.caption_label)
        centre.addWidget(self.command_box)
        centre.addWidget(self.log_label)
        centre.addWidget(self.status_label)
        centre.addWidget(self.controls)

        row = QHBoxLayout()
        row.setSpacing(16)
        # Left column: the clock in the middle, timers (when there are any) at the bottom.
        left = self._column(self.clock_panel)
        left.addWidget(self.timer_panel)
        row.addLayout(left)
        row.addLayout(centre, stretch=1)
        row.addLayout(self._column(self.system_panel))

        # The whole window: top bar first, then the three columns below it.
        page = QVBoxLayout(self)
        page.setContentsMargins(24, 16, 24, 24)
        page.addLayout(self._build_top_bar())
        page.addLayout(row, stretch=1)

        # The CHAT LOG panel (L key) floats over the eye rather than taking a
        # place in the layout, so opening it never moves anything else.
        self.chat_log_panel = ChatLogPanel(self)

    def _build_top_bar(self) -> QHBoxLayout:
        """'E.V.E' on the left; hide (-) and close (X) buttons on the right."""
        title = QLabel("E.V.E.")
        title.setFont(theme.font(16, bold=True))
        title.setStyleSheet(f"color: {theme.CYAN.name()}; background: transparent;")

        hide_button = self._corner_button("–", "Hide E.V.E. (or press H). She keeps running: "
                                          "bring her back from the tray icon or say \"Eve, show yourself\"",
                                          theme.CYAN)
        hide_button.clicked.connect(self.hide_hud)
        close_button = self._corner_button("X", "Quit E.V.E.", theme.DANGER)
        # When clicked, play the shutdown animation, which then closes the window.
        close_button.clicked.connect(self.shutdown)

        bar = QHBoxLayout()
        bar.addWidget(title)
        bar.addStretch()  # pushes the buttons all the way to the right
        bar.addWidget(hide_button)
        bar.addWidget(close_button)
        return bar

    @staticmethod
    def _corner_button(text: str, tip: str, hover: QColor) -> QPushButton:
        button = QPushButton(text)
        button.setFixedSize(32, 32)
        button.setFont(theme.font(12, bold=True))
        button.setCursor(Qt.PointingHandCursor)
        button.setToolTip(tip)
        button.setFocusPolicy(Qt.NoFocus)  # so key presses still reach the window
        # A stylesheet is like CSS for Qt: how the button looks normally and on hover.
        text_on_hover = theme.BACKGROUND.name() if hover == theme.CYAN else "white"
        button.setStyleSheet(f"""
            QPushButton {{
                color: {theme.CYAN.name()};
                background: transparent;
                border: 1px solid {theme.CYAN_DIM.name(QColor.HexArgb)};
                border-radius: 6px;
            }}
            QPushButton:hover {{
                color: {text_on_hover};
                background: {hover.name()};
                border-color: {hover.name()};
            }}
        """)
        return button

    # --- Fitting the layout to the window's size --------------------------------
    # Wide: clock and CPU panels at the sides, full button labels.
    # Narrow: those two panels hide and the buttons get short labels, so the
    # HUD can be made much smaller. The timers panel still appears when a
    # timer is running, and the window won't go narrower than it needs then.

    def _full_width(self) -> int:
        """The narrowest the WIDE layout fits in."""
        centre = max(self.eye.minimumWidth(), self.controls.width_needed(compact=False))
        return MARGINS + centre + 2 * (theme.PANEL_WIDTH + COLUMN_GAP) + SLACK

    def _compact_width(self) -> int:
        """The narrowest the NARROW layout fits in (wider while a timer shows)."""
        centre = max(self.eye.minimumWidth(), self.controls.width_needed(compact=True))
        timers = theme.PANEL_WIDTH + COLUMN_GAP if self.timer_panel.isVisibleTo(self) else 0
        return MARGINS + centre + timers + SLACK

    def _fit_layout(self) -> None:
        compact = self.width() < self._full_width()
        if compact != self._compact:
            self._compact = compact
            self.clock_panel.setVisible(not compact)
            self.system_panel.setVisible(not compact)
            self.controls.set_compact(compact)
        # Setting a minimum ourselves stops Qt using the wide layout's minimum,
        # which is what lets the window be dragged smaller than that.
        height = self.layout().minimumSize().height()
        self.setMinimumSize(self._compact_width(), height)

    def _check_timers_panel(self) -> None:
        """The timers panel shows and hides itself; when it does, re-fit."""
        showing = self.timer_panel.isVisibleTo(self)
        if showing != self._timers_showing:
            self._timers_showing = showing
            self._fit_layout()

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
        text = (f'<span style="color:{theme.TEXT_DIM.name()}">STATUS //</span> '
                f'<span style="color:{colour.name()}">{word}</span>')
        if self._mode:
            text += f'<span style="color:{theme.TEXT_DIM.name()}">&nbsp;&nbsp;·&nbsp;&nbsp;MODE // {self._mode}</span>'
        if self._wake:
            text += f'<span style="color:{theme.TEXT_DIM.name()}">&nbsp;&nbsp;·&nbsp;&nbsp;WAKE // {self._wake}</span>'
        if self._muted:
            text += (f'<span style="color:{theme.TEXT_DIM.name()}">&nbsp;&nbsp;·&nbsp;&nbsp;MIC // </span>'
                     f'<span style="color:{theme.DANGER.name()}">MUTED</span>')
        if self._gemini:
            text += (f'<span style="color:{theme.TEXT_DIM.name()}">&nbsp;&nbsp;·&nbsp;&nbsp;GEMINI // </span>'
                     f'{self._gemini}')
        self.status_label.setText(text)

    def show_mode(self, mode: str) -> None:
        """Show the brain's mode (e.g. "FAST" or "THINK") next to the status."""
        self._mode = mode
        self._show_state(self.animator.state)
        self.controls.show_mode(mode)
        self._fit_layout()   # the button's new label may need a little more room

    def show_wake(self, on: bool) -> None:
        """Show whether she's listening for her name: WAKE // ON or OFF."""
        self._wake = "ON" if on else "OFF"
        self._show_state(self.animator.state)
        self.controls.show_wake(on)

    def show_muted(self, muted: bool) -> None:
        """Microphone muted: MIC // MUTED in red, and the MIC button goes red."""
        self._muted = muted
        self._show_state(self.animator.state)
        self.controls.show_muted(muted)

    def _update_gemini_count(self) -> None:
        """GEMINI // 12/15 LEFT · 84 TODAY: amber at 3 left or fewer, red at 0."""
        count = self.rate_count
        left = count.left()
        colour = (theme.DANGER if left == 0 else theme.WARNING if left <= 3 else theme.CYAN).name()
        text = (f'<span style="color:{colour}">{left}/{count.per_minute} LEFT</span>'
                f'<span style="color:{theme.TEXT_DIM.name()}">&nbsp;·&nbsp;{count.today()} TODAY</span>')
        if text != self._gemini:   # only redraw when it changed
            self._gemini = text
            self._show_state(self.animator.state)

    def show_caption(self, who: str, text: str) -> None:
        """
        Show a caption under the eye: your words on one line, her reply below.
        `who` is "you" or "eve". When you start talking again, her old reply clears.
        """
        if who == "you":
            self._you_said = text
            self.typewriter.clear()   # also clears her line, through _on_typed
        else:
            self.typewriter.type(text, 0.0)

    def show_subtitle(self, sentence: str, seconds: float) -> None:
        """Type out the sentence she's saying, spread over `seconds`."""
        self.typewriter.type(sentence, seconds)

    def _on_typed(self, shown: str, rest: str) -> None:
        """The typewriter has shown a few more letters: redraw the caption."""
        self._eve_said = shown
        self._eve_rest = rest
        self._draw_caption()

    def _draw_caption(self) -> None:
        lines = []
        if self._you_said:
            # escape() stops symbols like < in what you said being read as HTML.
            lines.append(f'<span style="color:{theme.TEXT_DIM.name()}"><b>YOU &rsaquo;</b> '
                         f'{escape(self._you_said)}</span>')
        if self._eve_said or self._eve_rest:
            # While she's still "typing": a block cursor, then the rest of the
            # sentence in transparent ink (it takes up space but can't be seen).
            typing = ""
            if self._eve_rest:
                typing = (f'<span style="color:{theme.CYAN.name()}">&#9612;</span>'
                          f'<span style="color:transparent">{escape(self._eve_rest[1:])}</span>')
            lines.append(f'<span style="color:{theme.CYAN.name()}"><b>E.V.E. &rsaquo;</b> '
                         f'{escape(self._eve_said)}</span>{typing}')
        self.caption_label.setText("<br>".join(lines))

    # --- Hiding and showing (E.V.E. keeps running either way) ----------------

    def hide_hud(self) -> None:
        """Take the window off screen. Voice, wake word and timers carry on."""
        if not self.isVisible() or self.shutdown_sequence.running:
            return
        window_memory.save(self.geometry())
        if self.command_box.isVisible():
            self.command_box.close_box()   # don't leave a half-typed message waiting
        self.hide()
        self.event_log.log("Display hidden. Say \"Eve, show yourself\" or use the tray icon", "HUD")
        self.visibility_changed.emit(False)

    def show_hud(self) -> None:
        """Bring the window back, in front, with the keyboard on it (so Space works)."""
        if self.shutdown_sequence.running:
            return
        was_hidden = not self.isVisible()
        self.show()
        self.showNormal()   # in case Windows minimised it
        self.raise_()
        self.activateWindow()
        self.setFocus()
        if was_hidden:
            self.event_log.log("Display back", "HUD")
            self.visibility_changed.emit(True)

    def toggle_hud(self) -> None:
        self.hide_hud() if self.isVisible() else self.show_hud()

    # --- The CHAT LOG panel (L key, LOG button, "Eve, show the chat log") ------

    def show_chat_log(self, open_it: bool) -> None:
        self._place_chat_log()
        self.chat_log_panel.set_open(open_it)
        self.controls.log.setChecked(open_it)

    def toggle_chat_log(self) -> None:
        self.show_chat_log(not self.chat_log_panel.isVisible())

    def _place_chat_log(self) -> None:
        """Lay the panel exactly over the eye (called again whenever the window resizes)."""
        self.chat_log_panel.setGeometry(self.eye.geometry().adjusted(4, 4, -4, -4))

    def shutdown(self) -> None:
        """Play the shutdown animation, then fade out and quit."""
        self.boot.running = False   # in case we're shut down mid-boot
        window_memory.save(self.geometry())
        self.shutdown_sequence.start()

    def _fade_out(self) -> None:
        # QPropertyAnimation smoothly changes a property over time:
        # here the whole window's opacity, from fully visible to invisible.
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(400)
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self.close)
        # Hiding the window no longer ends the program (main.py turns that
        # off, so hiding her doesn't quit her), so we end it ourselves here.
        self._fade.finished.connect(QApplication.instance().quit)
        self._fade.start()

    def _follow_mouse(self) -> None:
        """Turn the mouse position into a -1..1 'look' direction for the eye."""
        eye_centre = self.eye.mapToGlobal(self.eye.rect().center())
        offset = QCursor.pos() - eye_centre
        reach = 600  # pixels from the eye at which it's looking fully sideways
        self.animator.set_gaze(offset.x() / reach, offset.y() / reach)

    def _log_state(self, state: EyeState) -> None:
        """Write a line in the feed for a state picked with the test keys 1-5.
        (Real state changes from the voice write their own [VOICE] lines.)"""
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
        if event.key() == Qt.Key_Space:
            # Holding a key makes Windows repeat it; only react to the first press.
            if not event.isAutoRepeat():
                self.talk_pressed.emit()
            return
        key = event.text().lower()
        if key in STATE_KEYS:
            self.animator.set_state(STATE_KEYS[key])
            self._log_state(STATE_KEYS[key])
        elif key == "b":
            self.boot.start()  # replay the whole startup, text and all
        elif key == "t":
            self.timers.add(TEST_TIMER_SECONDS, "test")   # try the countdown and announcement
            self.event_log.log(f"Test timer: {TEST_TIMER_SECONDS} seconds", "TIMER")
        elif key == "m":
            self.mode_toggle_pressed.emit()
        elif key == "w":
            self.wake_toggle_pressed.emit()
        elif key == "n":
            self.mute_toggle_pressed.emit()
        elif key == "/":
            self.command_box.open()   # from now, typing goes into the box
        elif key == "h":
            self.hide_hud()
        elif key == "l":
            self.toggle_chat_log()
        elif event.key() == Qt.Key_Escape:
            self.shutdown()

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self.talk_released.emit()

    # --- Mouse: drag an edge to resize, anywhere else to move ---------------
    # With no title bar or borders, Windows doesn't know where to grab the
    # window, so we tell it: on a mouse press we work out whether it's on an
    # edge, then hand the drag to Windows itself (startSystemResize /
    # startSystemMove), which makes it as smooth as a normal window.

    def _edges_at(self, point: QPoint):
        """Which edges (if any) a point inside the window is close to."""
        edges = Qt.Edge(0)
        if point.x() < EDGE:
            edges |= Qt.LeftEdge
        elif point.x() >= self.width() - EDGE:
            edges |= Qt.RightEdge
        if point.y() < EDGE:
            edges |= Qt.TopEdge
        elif point.y() >= self.height() - EDGE:
            edges |= Qt.BottomEdge
        return edges

    def _update_edge_cursor(self) -> None:
        """Show <-> style arrows while the mouse is over an edge or corner."""
        point = self.mapFromGlobal(QCursor.pos())
        inside = self.rect().contains(point)
        cursor = EDGE_CURSORS.get(self._edges_at(point)) if inside and self._drag_offset is None else None
        if cursor != self._edge_cursor:
            self._edge_cursor = cursor
            if cursor is None:
                self.unsetCursor()
            else:
                self.setCursor(cursor)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        edges = self._edges_at(event.position().toPoint())
        handle = self.windowHandle()
        if edges and handle and handle.startSystemResize(edges):
            return
        if not edges and handle and handle.startSystemMove():
            return
        # Windows said no to both: move it ourselves instead, the old way.
        self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None

    # Whenever the window is moved or resized, save it (once it's been still a moment).
    def moveEvent(self, event):
        super().moveEvent(event)
        if self.isVisible():
            self._save_timer.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._compact is not None:   # (not before __init__ has finished)
            self._fit_layout()
            self._place_chat_log()
        if self.isVisible():
            self._save_timer.start()


if __name__ == "__main__":
    # Visual test: run  .venv\Scripts\python -m ui.hud_window
    # Keys: 1-5 states, B replay startup, H hide (comes back after 3 seconds
    # here, as there's no tray icon), Esc quit. Drag to move, drag edges to resize.
    import sys

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    window = HudWindow()
    window.visibility_changed.connect(lambda showing: showing or QTimer.singleShot(3000, window.show_hud))
    window.show()
    sys.exit(app.exec())
