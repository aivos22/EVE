"""
The CHAT LOG panel: the last 10 chats, shown over the eye.

    CHAT LOG · last 10                                   L to close
    14:02  YOU  what's the weather tomorrow
           EVE  Light rain in the morning, sir, clearing by noon.

Press L (or the LOG button) to show and hide it. It scrolls if the chats
don't fit. The chats come from brain/chat_log.py; this file only shows them.
While it's open it checks twice a second for new chats, so a reply
appears in it as soon as she's finished saying it.
"""

from html import escape

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFrame, QLabel, QTextBrowser, QVBoxLayout

from brain.chat_log import KEEP, get_chat_log, nice_time
from ui import theme


class ChatLogPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.chat_log = get_chat_log()
        self._shown_version = -1
        self.setObjectName("chatLog")
        self.setStyleSheet(f"""
            #chatLog {{
                background: {theme.BACKGROUND.name(QColor.HexArgb)};
                border: 1px solid {theme.CYAN_DIM.name(QColor.HexArgb)};
                border-radius: 10px;
            }}
        """)

        title = QLabel(f'CHAT LOG <span style="color:{theme.TEXT_DIM.name()}">· last {KEEP}'
                       f'&nbsp;&nbsp;&nbsp;(L to close)</span>')
        title.setFont(theme.font(11, bold=True))
        title.setStyleSheet(f"color: {theme.CYAN.name()}; background: transparent; border: none;")

        self.text = QTextBrowser()
        self.text.setFont(theme.font(11))
        self.text.setOpenLinks(False)
        # No keyboard focus, so Space, L, H etc. still reach the window.
        # (The mouse wheel still scrolls it.)
        self.text.setFocusPolicy(Qt.NoFocus)
        self.text.setStyleSheet(f"""
            QTextBrowser {{ background: transparent; border: none; color: {theme.TEXT.name()}; }}
            QScrollBar:vertical {{ background: transparent; width: 8px; }}
            QScrollBar::handle:vertical {{ background: {theme.CYAN_DIM.name(QColor.HexArgb)};
                                           border-radius: 4px; min-height: 20px; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.addWidget(title)
        layout.addWidget(self.text, stretch=1)

        # Check for new chats while open (cheap: just compares a number).
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh)
        self.hide()

    def toggle(self) -> None:
        self.set_open(not self.isVisible())

    def set_open(self, open_it: bool) -> None:
        if open_it:
            self._shown_version = -1   # always redraw when opened
            self._refresh()
            self.show()
            self.raise_()
            self._refresh_timer.start(500)
        else:
            self.hide()
            self._refresh_timer.stop()

    def _refresh(self) -> None:
        version = self.chat_log.version
        if version == self._shown_version:
            return
        self._shown_version = version
        chats = self.chat_log.all()
        if not chats:
            self.text.setHtml(f'<p style="color:{theme.TEXT_DIM.name()}">No chats yet. '
                              "Say something to E.V.E. and it'll appear here.</p>")
            return
        dim, cyan = theme.TEXT_DIM.name(), theme.CYAN.name()
        rows = []
        for chat in chats:
            # escape() stops symbols like < in a message being read as HTML.
            rows.append(
                f'<tr><td style="color:{dim}; padding-right:10px">{nice_time(chat["time"])}</td>'
                f'<td style="color:{dim}; padding-right:8px"><b>YOU</b></td>'
                f'<td style="color:{theme.TEXT.name()}">{escape(chat["you"])}</td></tr>'
                f'<tr><td></td><td style="color:{cyan}; padding-right:8px"><b>EVE</b></td>'
                f'<td style="color:{cyan}; padding-bottom:10px">{escape(chat["eve"])}</td></tr>')
        self.text.setHtml(f'<table cellspacing="0" cellpadding="1">{"".join(rows)}</table>')
        # Newest at the bottom, so scroll down to it.
        bar = self.text.verticalScrollBar()
        bar.setValue(bar.maximum())
