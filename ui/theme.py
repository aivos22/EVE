"""
All of E.V.E.'s look in one place: colours, fonts and sizes.

Change a value here and every part of the HUD picks it up,
so you never have to hunt through drawing code to restyle things.
"""

from PySide6.QtGui import QColor, QFont

# --- Colours -------------------------------------------------------------
# QColor(red, green, blue, alpha). Alpha is see-through-ness: 0 = invisible, 255 = solid.

BACKGROUND = QColor(5, 12, 18, 215)       # very dark blue-black, slightly see-through
PANEL_BG = QColor(10, 25, 35, 160)        # side panels, a bit lighter and more see-through
CYAN = QColor(0, 229, 255)                # main accent colour
CYAN_DIM = QColor(0, 229, 255, 90)        # faint cyan for borders and inactive parts
CYAN_GLOW = QColor(0, 229, 255, 60)       # very soft cyan used for glows
TEXT = QColor(190, 245, 255)              # light cyan-white for readable text
TEXT_DIM = QColor(120, 180, 195)          # greyer text for labels
WARNING = QColor(255, 170, 0)             # amber, for things like high CPU use

# --- Fonts ---------------------------------------------------------------
# Consolas ships with Windows and gives a techy, monospaced look.
FONT_FAMILY = "Consolas"


def font(size: int, bold: bool = False) -> QFont:
    """Make a font in E.V.E.'s style at the given point size."""
    f = QFont(FONT_FAMILY, size)
    f.setBold(bold)
    f.setLetterSpacing(QFont.PercentageSpacing, 110)  # spread letters out a little
    return f


# --- Sizes ---------------------------------------------------------------
WINDOW_WIDTH = 1100
WINDOW_HEIGHT = 700
CORNER_RADIUS = 18        # how rounded the window corners are
PANEL_WIDTH = 220         # width of each side panel
FPS = 60                  # animation frames per second


if __name__ == "__main__":
    # Quick self-test: run  .venv\Scripts\python -m ui.theme
    print("Theme loaded.")
    print(f"  Accent colour: {CYAN.name()}")
    print(f"  Font: {FONT_FAMILY}")
    print(f"  Window: {WINDOW_WIDTH} x {WINDOW_HEIGHT} at {FPS} fps")
