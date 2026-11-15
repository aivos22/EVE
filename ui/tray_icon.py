"""
E.V.E.'s icon in the system tray (the small icons by the clock, bottom-right
of the taskbar). It's how you get her back after hiding the display.

    left-click    show / hide the display
    right-click   a menu: Show / Hide, Mute microphone, Wake word on/off, Quit

Windows sometimes tucks new tray icons behind the little ^ arrow. Drag it
out onto the taskbar to keep it in view.

The picture is drawn here with QPainter (a small cyan eye), so there's no
image file to keep track of.

This file only shows the icon and reports clicks. main.py connects it up.
"""

from PySide6.QtCore import QObject, QPointF, Qt, Signal
from PySide6.QtGui import QAction, QIcon, QPainter, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ui import theme


def _eye_icon() -> QIcon:
    """A 64x64 picture of her eye: dark disc, cyan ring, glowing pupil."""
    size = 64
    picture = QPixmap(size, size)
    picture.fill(Qt.transparent)
    p = QPainter(picture)
    p.setRenderHint(QPainter.Antialiasing)
    centre = QPointF(size / 2, size / 2)
    p.setPen(QPen(theme.CYAN, 4))
    p.setBrush(theme.BACKGROUND)
    p.drawEllipse(centre, 28, 28)
    p.setPen(QPen(theme.CYAN_DIM, 3))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(centre, 18, 18)
    glow = QRadialGradient(centre, 10)
    glow.setColorAt(0, theme.CYAN)
    glow.setColorAt(1, Qt.transparent)
    p.setPen(Qt.NoPen)
    p.setBrush(glow)
    p.drawEllipse(centre, 10, 10)
    p.end()
    return QIcon(picture)


class TrayIcon(QObject):
    toggle_requested = Signal()        # show the display if hidden, hide it if showing
    wake_toggle_requested = Signal()   # switch the wake word on / off
    mute_toggle_requested = Signal()   # mute / unmute the microphone
    quit_requested = Signal()          # shut E.V.E. down completely

    def __init__(self, parent=None):
        super().__init__(parent)
        self.icon = QSystemTrayIcon(_eye_icon(), self)
        self._told_about_hiding = False

        self.menu = QMenu()
        self.show_action = QAction("Hide display", self.menu)
        self.show_action.triggered.connect(self.toggle_requested)
        self.wake_action = QAction("Wake word: —", self.menu)
        self.wake_action.setEnabled(False)   # until the voice says whether it's on
        self.wake_action.triggered.connect(self.wake_toggle_requested)
        self.mute_action = QAction("Mute microphone", self.menu)
        self.mute_action.triggered.connect(self.mute_toggle_requested)
        self._showing = True
        self._muted = False
        quit_action = QAction("Quit E.V.E.", self.menu)
        quit_action.triggered.connect(self.quit_requested)
        self.menu.addAction(self.show_action)
        self.menu.addAction(self.mute_action)
        self.menu.addAction(self.wake_action)
        self.menu.addSeparator()
        self.menu.addAction(quit_action)
        self.icon.setContextMenu(self.menu)   # right-click

        self.icon.activated.connect(self._clicked)
        # Clicking the bubble (see display_changed) brings her back too.
        self.icon.messageClicked.connect(self.toggle_requested)
        self.display_changed(True)

    @staticmethod
    def available() -> bool:
        """False on the rare setup with no tray: she still works by voice."""
        return QSystemTrayIcon.isSystemTrayAvailable()

    def show(self) -> None:
        self.icon.show()

    def hide(self) -> None:
        self.icon.hide()   # called when she quits, so the icon doesn't linger

    def _clicked(self, reason) -> None:
        # Trigger = a normal left-click. (Right-click opens the menu by itself.)
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.toggle_requested.emit()

    # --- Kept up to date by main.py ------------------------------------------

    def display_changed(self, showing: bool) -> None:
        self._showing = showing
        self.show_action.setText("Hide display" if showing else "Show display")
        self._tooltip()
        if not showing and not self._told_about_hiding:
            # The first time only: a little bubble saying where she went.
            self._told_about_hiding = True
            self.icon.showMessage("E.V.E. is still running",
                                  "Click here or say \"Eve, show yourself\" to bring the display back.",
                                  _eye_icon(), 5000)

    def muted_changed(self, muted: bool) -> None:
        self._muted = muted
        self.mute_action.setText("Unmute microphone" if muted else "Mute microphone")
        self._tooltip()

    def _tooltip(self) -> None:
        if self._muted:
            text = "E.V.E. (microphone muted)" if self._showing else "E.V.E. (hidden, microphone muted)"
        else:
            text = "E.V.E." if self._showing else "E.V.E. (hidden, still listening)"
        self.icon.setToolTip(text)

    def wake_changed(self, on: bool) -> None:
        self.wake_action.setText("Wake word: ON (click to turn off)" if on else "Wake word: OFF (click to turn on)")
        self.wake_action.setEnabled(True)
