"""
Remembers where the HUD was and how big it was, so she opens the same way
next time. Saved in data/hud_window.json, a tiny file like:

    {"x": 300, "y": 120, "width": 1200, "height": 760}

Delete the file to go back to the normal size in the middle of the screen.

If the saved spot is no longer on any screen (e.g. a monitor was unplugged),
it's ignored, so she can never open somewhere you can't see her.
"""

import json
import logging

from PySide6.QtCore import QRect
from PySide6.QtGui import QGuiApplication

from paths import DATA_DIR

MEMORY_FILE = DATA_DIR / "hud_window.json"
MIN_VISIBLE = 200   # pixels of her (each way) that must be on a screen to use the saved spot

diary = logging.getLogger("eve")


def load() -> QRect | None:
    """The saved size and position, or None if there isn't a usable one."""
    try:
        saved = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
        rect = QRect(int(saved["x"]), int(saved["y"]), int(saved["width"]), int(saved["height"]))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError) as error:
        diary.warning(f"Ignoring {MEMORY_FILE.name}: {error!r}")
        return None
    for screen in QGuiApplication.screens():
        overlap = screen.availableGeometry().intersected(rect)
        if overlap.width() >= MIN_VISIBLE and overlap.height() >= MIN_VISIBLE:
            return rect
    return None   # off every screen: use the default instead


def save(rect: QRect) -> None:
    """Write the size and position down. A failure here is never worth a crash."""
    try:
        MEMORY_FILE.write_text(json.dumps({"x": rect.x(), "y": rect.y(),
                                           "width": rect.width(), "height": rect.height()}),
                               encoding="utf-8")
    except OSError as error:
        diary.warning(f"Couldn't save the window size: {error!r}")
