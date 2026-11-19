"""
The WHITEBOARD: where E.V.E. writes out worked answers, one step at a time.

    WHITEBOARD · Solve 2x + 5 = 17                  [POP OUT] [X]
     (1)  2x + 5 = 17
          the question
     (2)  2x = 12
          take 5 from both sides
     (3) [ x = 6 ]                      <- the answer gets a box

Each line of maths is "written" left to right with a glowing pen tip; the
note underneath fades in after it. Click the board to skip to the end.

Two ways to see it:
  - docked: it lies over the eye, like the chat log (that's the default)
  - popped out: POP OUT turns it into its own see-through window, like the
    HUD. Drag its title strip to move it (to another screen too) and its
    edges to resize it. DOCK puts it back over the eye.
Both are see-through (BOARD_ALPHA below says how much).
It remembers which you chose, and where the popped-out window was
(data/whiteboard_window.json).

D (or the board's X) shows and hides it. Other code writes on it with
    whiteboard.write("Solve 2x + 5 = 17", [("2x + 5 = 17", "the question"), ...], answer="x = 6")
The maths is LaTeX (see ui/maths_image.py); a note is plain words.

Test it alone:  .venv\\Scripts\\python -m ui.whiteboard
"""

import json
import logging
from dataclasses import dataclass

from PySide6.QtCore import QElapsedTimer, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QImage, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from paths import DATA_DIR
from ui import theme, window_memory
from ui.maths_image import HANDWRITING_FONT, picture

WINDOW_FILE = DATA_DIR / "whiteboard_window.json"

# How it looks and how fast she writes. Change these to taste.
MATHS_SIZE = 24        # font size of the maths (points)
NOTE_SIZE = 15         # font size of the notes under each line
PEN_SPEED = 380        # how fast the pen moves along a line of maths (pixels per second)
NOTE_SECONDS = 0.45    # how long a note takes to fade in
PAUSE_SECONDS = 0.35   # breath between steps
MARGIN = 26            # space round the edge of the board
NUMBER_WIDTH = 42      # room on the left for the step numbers
ROW_GAP = 20           # space between steps

# How see-through the board's background is: 0 = fully clear, 255 = solid.
# Lower lets more of the eye (or your desktop, when popped out) show through,
# but light text gets harder to read over bright things behind it.
BOARD_ALPHA = 150
EDGE = 8   # popped out: how close to an edge (pixels) the mouse must be to resize

INK = theme.TEXT
NOTE_INK = theme.TEXT_DIM
ANSWER_INK = QColor(255, 215, 100)   # warm gold, like her speaking colour

DEMO = ("Solve x² + 3x − 10 = 0", [
    (r"x^2 + 3x - 10 = 0", "the question: a quadratic, so a = 1, b = 3, c = -10"),
    (r"x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}", "use the quadratic formula"),
    (r"x = \frac{-3 \pm \sqrt{9 + 40}}{2}", "put the numbers in"),
    (r"x = \frac{-3 \pm 7}{2}", "the square root of 49 is 7"),
], r"x = 2 \quad or \quad x = -5")

diary = logging.getLogger("eve")


@dataclass
class Step:
    maths: str
    note: str = ""
    answer: bool = False
    image: QImage | None = None


class _Board(QWidget):
    """The writing surface. It grows taller as steps are added; the scroll area around it scrolls."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.steps: list[Step] = []
        self.clock = 0.0        # seconds since writing started
        self._starts: list[float] = []   # when each step starts being written
        self._rows: list[QRectF] = []    # where each step sits
        self.note_font = QFont(HANDWRITING_FONT, NOTE_SIZE)
        self.number_font = theme.font(11, bold=True)
        self.setCursor(Qt.PointingHandCursor)

    # --- What's on it ---------------------------------------------------------

    def set_steps(self, steps: list[Step]) -> None:
        scale = self.devicePixelRatioF() or 1.0
        for step in steps:
            step.image = picture(step.maths, ANSWER_INK if step.answer else INK, MATHS_SIZE, scale)
        self.steps = steps
        self.clock = 0.0
        self._starts, start = [], 0.0
        for step in steps:
            self._starts.append(start)
            start += self._writing_time(step) + (NOTE_SECONDS if step.note else 0) + PAUSE_SECONDS
        self.total_time = start
        self._lay_out()

    def _writing_time(self, step: Step) -> float:
        width = step.image.width() / step.image.devicePixelRatio()
        return max(0.35, width / PEN_SPEED)

    @property
    def finished(self) -> bool:
        return not self.steps or self.clock >= self.total_time

    def current_row(self) -> QRectF | None:
        """Where the step being written now is (for scrolling to it)."""
        for index in reversed(range(len(self.steps))):
            if self.clock >= self._starts[index]:
                return self._rows[index]
        return None

    # --- Where things go --------------------------------------------------------

    def _lay_out(self) -> None:
        fm = QFontMetricsF(self.note_font)
        room = max(100, self.width() - 2 * MARGIN - NUMBER_WIDTH)
        y = MARGIN
        self._rows = []
        for step in self.steps:
            width, height = self._maths_size(step, room)
            note_height = fm.boundingRect(QRectF(0, 0, room, 10_000), Qt.TextWordWrap, step.note).height() \
                if step.note else 0
            row_height = height + (note_height + 4 if step.note else 0)
            self._rows.append(QRectF(MARGIN, y, room + NUMBER_WIDTH, row_height))
            y += row_height + ROW_GAP
        self.setMinimumHeight(int(y + MARGIN))

    def _maths_size(self, step: Step, room: float) -> tuple[float, float]:
        """The maths picture's size on screen: shrunk to fit if it's wider than the board."""
        ratio = step.image.devicePixelRatio()
        width, height = step.image.width() / ratio, step.image.height() / ratio
        if width > room:
            height *= room / width
            width = room
        return width, height

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.steps:
            self._lay_out()

    # --- Drawing ----------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        if not self.steps:
            painter.setPen(NOTE_INK)
            painter.setFont(self.note_font)
            painter.drawText(self.rect().adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN), Qt.TextWordWrap,
                             "Nothing on the board yet. Ask me how to solve something, sir.")
            return
        for index, step in enumerate(self.steps):
            local = self.clock - self._starts[index]
            if local < 0:
                break   # not started yet (nor are any after it)
            self._draw_step(painter, index, step, local)

    def _draw_step(self, painter: QPainter, index: int, step: Step, local: float) -> None:
        row = self._rows[index]
        left = row.left() + NUMBER_WIDTH
        width, height = self._maths_size(step, row.width() - NUMBER_WIDTH)
        maths_area = QRectF(left, row.top(), width, height)

        # The step number in a small circle (the answer gets a tick instead).
        circle = QRectF(row.left() + 2, row.top() + height / 2 - 13, 26, 26)
        colour = ANSWER_INK if step.answer else theme.CYAN
        painter.setPen(QPen(colour if step.answer else theme.CYAN_DIM, 1.5))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(circle)
        painter.setPen(colour)
        painter.setFont(self.number_font)
        painter.drawText(circle, Qt.AlignCenter, "✓" if step.answer else str(index + 1))

        # The maths, uncovered left to right as the pen moves.
        written = min(1.0, local / self._writing_time(step))
        painter.save()
        painter.setClipRect(QRectF(left, row.top() - 4, width * written, height + 8))
        painter.drawImage(maths_area, step.image)
        painter.restore()
        if written < 1.0:
            self._draw_pen(painter, QPointF(left + width * written, row.top() + height * 0.55))
        elif step.answer:
            painter.setPen(QPen(ANSWER_INK, 1.5))
            painter.drawRoundedRect(maths_area.adjusted(-8, -4, 8, 4), 8, 8)

        # The note underneath, fading in once the maths is done.
        if step.note and written >= 1.0:
            fade = min(1.0, (local - self._writing_time(step)) / NOTE_SECONDS)
            painter.setOpacity(max(0.0, fade))
            painter.setPen(NOTE_INK)
            painter.setFont(self.note_font)
            painter.drawText(QRectF(left, row.top() + height + 4, row.width() - NUMBER_WIDTH, 10_000),
                             Qt.TextWordWrap, step.note)
            painter.setOpacity(1.0)

    def _draw_pen(self, painter: QPainter, tip: QPointF) -> None:
        """A small glowing dot where the 'pen' is."""
        glow = QRadialGradient(tip, 12)
        glow.setColorAt(0, QColor(0, 229, 255, 200))
        glow.setColorAt(1, QColor(0, 229, 255, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(tip, 12, 12)
        painter.setBrush(QColor(255, 255, 255))
        painter.drawEllipse(tip, 2.5, 2.5)

    def mousePressEvent(self, event):
        # Click to skip the writing and show everything now.
        if self.steps:
            self.clock = self.total_time
            self.update()


class Whiteboard(QFrame):
    """The board with its title bar. Lives over the eye, or in its own window when popped out."""

    popped_changed = Signal(bool)   # True = now its own window, False = back over the eye

    def __init__(self, hud: QWidget):
        super().__init__(hud)
        self._hud = hud
        self.popped = False
        self.setObjectName("whiteboard")
        self.setMinimumSize(320, 260)

        self.title = QLabel()
        self.title.setFont(theme.font(11, bold=True))
        self.title.setStyleSheet(f"color: {theme.CYAN.name()}; background: transparent; border: none;")
        self.title.setTextFormat(Qt.RichText)
        self.pop_button = self._button("POP OUT", "Put the whiteboard in its own window")
        self.pop_button.clicked.connect(lambda: self.dock() if self.popped else self.pop_out())
        close_button = self._button("X", "Close the whiteboard (or press D)")
        close_button.clicked.connect(lambda: self.set_open(False))

        header = QHBoxLayout()
        header.addWidget(self.title, stretch=1)
        header.addWidget(self.pop_button)
        header.addWidget(close_button)

        self.board = _Board()
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.board)
        self.scroll.setWidgetResizable(True)
        # No keyboard focus, so Space, D, L etc. still reach the main window.
        self.scroll.setFocusPolicy(Qt.NoFocus)
        self.scroll.setStyleSheet(f"""
            QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
            QScrollBar:vertical {{ background: transparent; width: 8px; }}
            QScrollBar::handle:vertical {{ background: {theme.CYAN_DIM.name(QColor.HexArgb)};
                                           border-radius: 4px; min-height: 20px; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.addLayout(header)
        layout.addWidget(self.scroll, stretch=1)

        # Writing animation: 60 frames a second, only while she's writing.
        self._frame_timer = QTimer(self)
        self._frame_timer.setInterval(1000 // theme.FPS)
        self._frame_timer.timeout.connect(self._next_frame)
        self._clock = QElapsedTimer()

        # Save the popped-out window's spot once it's been still for a moment.
        self._save_timer = QTimer(self, singleShot=True, interval=500)
        self._save_timer.timeout.connect(self._save_spot)

        self._subject = ""
        self._style()
        self._show_title()
        self.hide()
        self._start_popped = self._saved_popped()

    # --- Writing on it ------------------------------------------------------------

    def write(self, subject: str, steps: list[tuple[str, str]], answer: str = "") -> None:
        """Clear the board and write out `steps` [(maths, note), ...], then the boxed answer."""
        board_steps = [Step(str(maths), str(note or "")) for maths, note in steps]
        if answer:
            board_steps.append(Step(answer, answer=True))
        self._subject = subject
        self._show_title()
        self.set_open(True)
        self.board.set_steps(board_steps)
        self.scroll.verticalScrollBar().setValue(0)
        self._clock.start()
        self._frame_timer.start()
        diary.info(f"[BOARD] Writing {len(board_steps)} steps: {subject}")

    def write_demo(self) -> None:
        self.write(*DEMO)

    @property
    def will_pop_out(self) -> bool:
        """True if it's in (or will open in) its own window, rather than over the eye."""
        return self.popped or bool(self._start_popped)

    @property
    def empty(self) -> bool:
        return not self.board.steps

    def _next_frame(self) -> None:
        if self.board.clock < self.board.total_time:
            self.board.clock = self._clock.elapsed() / 1000
        row = self.board.current_row()
        if row is not None:   # keep the line being written in view
            self.scroll.ensureVisible(int(row.left()), int(row.bottom()), 0, MARGIN)
        self.board.update()
        if self.board.finished:
            self._frame_timer.stop()

    # --- Showing and hiding ---------------------------------------------------------

    def toggle(self) -> None:
        self.set_open(not self.isVisible())

    def set_open(self, open_it: bool) -> None:
        if not open_it:
            self.hide()
            return
        if self._start_popped is not None:   # the first time: open the way it was left last time
            popped, self._start_popped = self._start_popped, None
            if popped:
                self.pop_out()
                return
        self.show()
        self.raise_()

    def place(self, area: QRect) -> None:
        """Lay the board over `area` (the eye). Ignored while popped out."""
        if not self.popped:
            self.setGeometry(area)

    # --- Popping out and docking --------------------------------------------------------

    def pop_out(self) -> None:
        """Make it a window of its own."""
        self.popped = True
        self.setParent(None)
        # No Windows title bar, and a see-through background, like the HUD.
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)   # to show a resize arrow over the edges
        self.setAttribute(Qt.WA_ShowWithoutActivating)   # don't steal the keyboard when it appears
        self.setWindowTitle("E.V.E. Whiteboard")
        self.setWindowIcon(self._hud.windowIcon())
        self.setGeometry(window_memory.load(WINDOW_FILE) or self._beside_hud())
        self._style()
        self._show_title()
        self.show()
        self.raise_()
        self._save_spot()
        self.popped_changed.emit(True)

    def dock(self) -> None:
        """Put it back over the eye."""
        was_open = self.isVisible()
        self._save_spot(popped_out=False)
        self.popped = False
        self.setParent(self._hud)   # back inside the main window
        self.setCursor(Qt.ArrowCursor)
        self._style()
        self._show_title()
        self.popped_changed.emit(False)   # the main window places it over the eye
        if was_open:
            self.show()
            self.raise_()

    def _beside_hud(self) -> QRect:
        """Where it first pops out: just to the right of the main window, on the same screen."""
        hud = self._hud.frameGeometry()
        screen = (self._hud.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        width, height = 640, max(420, min(hud.height(), screen.height() - 40))
        x = min(hud.right() + 12, screen.right() - width)
        y = max(screen.top() + 20, min(hud.top(), screen.bottom() - height))
        return QRect(x, y, width, height)

    def _save_spot(self, popped_out: bool | None = None) -> None:
        if self.popped:
            window_memory.save(self.geometry(), WINDOW_FILE,
                               popped_out=self.popped if popped_out is None else popped_out)

    def _saved_popped(self) -> bool:
        try:
            return bool(json.loads(WINDOW_FILE.read_text(encoding="utf-8")).get("popped_out"))
        except (OSError, ValueError, AttributeError):
            return False

    def moveEvent(self, event):
        super().moveEvent(event)
        if self.popped and self.isVisible():
            self._save_timer.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.popped and self.isVisible():
            self._save_timer.start()

    # --- Popped out: drag the title strip to move, an edge to resize -------------

    def _edges_at(self, point) -> Qt.Edge:
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

    def mousePressEvent(self, event):
        # Clicks on the board itself are handled by the board (skip the
        # writing); this gets the clicks on the title strip and the border.
        if not self.popped or event.button() != Qt.LeftButton:
            return
        handle = self.windowHandle()
        if not handle:
            return
        point = event.position().toPoint()
        edges = self._edges_at(point)
        if edges:
            handle.startSystemResize(edges)   # Windows does the resizing, smoothly
        elif point.y() < self.scroll.geometry().top():
            handle.startSystemMove()

    def mouseMoveEvent(self, event):
        if not self.popped:
            return
        edges = self._edges_at(event.position().toPoint())
        horizontal = edges & (Qt.LeftEdge | Qt.RightEdge)
        vertical = edges & (Qt.TopEdge | Qt.BottomEdge)
        if horizontal and vertical:
            corner = edges in (Qt.LeftEdge | Qt.TopEdge, Qt.RightEdge | Qt.BottomEdge)
            self.setCursor(Qt.SizeFDiagCursor if corner else Qt.SizeBDiagCursor)
        elif horizontal:
            self.setCursor(Qt.SizeHorCursor)
        elif vertical:
            self.setCursor(Qt.SizeVerCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    def closeEvent(self, event):
        # The window's own X (when popped out) just hides it; E.V.E. carries on.
        event.ignore()
        self.hide()

    def keyPressEvent(self, event):
        # When popped out, keys land here. D or Esc closes the board; anything
        # else (Space to talk, M, N...) goes on to the main window as usual.
        if event.key() == Qt.Key_Escape or event.text().lower() == "d":
            self.hide()
        else:
            self._hud.keyPressEvent(event)

    def keyReleaseEvent(self, event):
        self._hud.keyReleaseEvent(event)

    # --- Looks ------------------------------------------------------------------------

    def _show_title(self) -> None:
        dim = theme.TEXT_DIM.name()
        subject = f' <span style="color:{theme.TEXT.name()}">· {self._subject}</span>' if self._subject else ""
        self.title.setText(f'WHITEBOARD{subject}&nbsp;&nbsp;<span style="color:{dim}">(D to close)</span>')
        self.pop_button.setText("DOCK" if self.popped else "POP OUT")
        self.pop_button.setToolTip("Put the whiteboard back over the eye" if self.popped
                                   else "Put the whiteboard in its own window")

    def _style(self) -> None:
        # Tinted glass: dark, but see-through (BOARD_ALPHA), docked or popped out.
        background = QColor(theme.BACKGROUND)
        background.setAlpha(BOARD_ALPHA)
        self.setStyleSheet(f"""
            #whiteboard {{
                background: {background.name(QColor.HexArgb)};
                border: 1px solid {theme.CYAN_DIM.name(QColor.HexArgb)};
                border-radius: 10px;
            }}
        """)

    def _button(self, text: str, tip: str) -> QPushButton:
        button = QPushButton(text)
        button.setToolTip(tip)
        button.setFont(theme.font(9, bold=True))
        button.setCursor(Qt.PointingHandCursor)
        button.setFocusPolicy(Qt.NoFocus)
        button.setStyleSheet(f"""
            QPushButton {{ color: {theme.CYAN.name()}; background: transparent; padding: 3px 9px;
                           border: 1px solid {theme.CYAN_DIM.name(QColor.HexArgb)}; border-radius: 5px; }}
            QPushButton:hover {{ background: {theme.CYAN_GLOW.name(QColor.HexArgb)}; }}
        """)
        return button


if __name__ == "__main__":
    # Visual test: a stand-in main window with the board over it, writing the demo.
    # Try POP OUT and DOCK, click the board to skip, D to hide and show, R to write it again.
    import sys

    from PySide6.QtWidgets import QApplication

    class _TestWindow(QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Whiteboard test (stand-in for the HUD)")
            self.setStyleSheet("background: #02070b;")
            self.resize(900, 700)
            self.whiteboard = Whiteboard(self)
            self.whiteboard.popped_changed.connect(lambda popped: popped or self._place())

        def _place(self):
            self.whiteboard.place(self.rect().adjusted(40, 40, -40, -40))

        def resizeEvent(self, event):
            self._place()

        def keyPressEvent(self, event):
            key = event.text().lower()
            if key == "d":
                self.whiteboard.toggle()
            elif key == "r":
                self.whiteboard.write_demo()

        def keyReleaseEvent(self, event):
            pass

    app = QApplication(sys.argv)
    window = _TestWindow()
    window.show()
    window.whiteboard.write_demo()
    sys.exit(app.exec())
