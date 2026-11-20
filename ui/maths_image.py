"""
Turns one line of maths into a picture, in a handwriting style.

    picture("x = \\frac{-b \\pm \\sqrt{b^2-4ac}}{2a}")   ->   a see-through image
                                                            of the formula, with a
                                                            proper fraction and root

The maths is written in LaTeX, the standard way computers write maths:
    x^2          x squared              \\frac{a}{b}   a over b
    \\sqrt{x}    square root of x       \\times        times sign
    \\div        divide sign            \\pi           pi
The drawing is done by matplotlib (a free maths-and-charts library). Letters
and numbers use Windows' "Ink Free" handwriting font, so it looks handwritten.

If a line isn't valid LaTeX, it's drawn as plain text instead of failing.

Test it alone:  .venv\\Scripts\\python -m ui.maths_image
(saves a sample picture into data/ and prints where it is)
"""

import logging
import re
from io import BytesIO
from pathlib import Path

import matplotlib

matplotlib.use("Agg")   # draw into memory only, never open matplotlib's own windows

from matplotlib import font_manager                        # noqa: E402
from matplotlib.backends.backend_agg import FigureCanvasAgg  # noqa: E402
from matplotlib.figure import Figure                        # noqa: E402
from PySide6.QtGui import QColor, QImage                    # noqa: E402

HANDWRITING_FONT = "Ink Free"
HANDWRITING_FILE = Path(r"C:\Windows\Fonts\Inkfree.ttf")

diary = logging.getLogger("eve")
# matplotlib grumbles about a few symbols it draws fine anyway (like big square roots).
logging.getLogger("matplotlib").setLevel(logging.ERROR)

_ready = False


def _set_up() -> None:
    """Tell matplotlib about the handwriting font, once."""
    global _ready
    if _ready:
        return
    style = {"mathtext.fontset": "dejavusans"}   # neat ordinary font if Ink Free is missing
    if HANDWRITING_FILE.exists():
        font_manager.fontManager.addfont(str(HANDWRITING_FILE))
        style = {"mathtext.fontset": "custom", "font.family": HANDWRITING_FONT}
        for kind in ("rm", "it", "bf", "sf"):   # upright, italic, bold, plain letters
            style[f"mathtext.{kind}"] = HANDWRITING_FONT
    matplotlib.rcParams.update(style)
    _ready = True


def picture(maths: str, colour: QColor, size: float = 26, scale: float = 1.0) -> QImage:
    """
    A see-through image of `maths` (LaTeX, with or without $ signs round it).
    size = font size in points. scale = the screen's sharpness setting
    (2 on a "200%" screen), so it isn't blurry there.
    """
    _set_up()
    maths = maths.strip().strip("$").strip() or " "
    # Gemini sometimes forgets a closing bracket, e.g. "\frac{15}{3": add it back.
    maths += "}" * max(0, maths.count("{") - maths.count("}"))
    try:
        image = _draw(f"${maths}$", colour, size, scale, as_maths=True)
    except Exception as error:   # still not valid LaTeX: write it as readably as we can
        diary.info(f"[BOARD] Couldn't read maths {maths!r} ({error}); writing it as text")
        image = _draw(_readable(maths), colour, size, scale, as_maths=False)
    image.setDevicePixelRatio(scale)
    return image


def _readable(maths: str) -> str:
    """Broken LaTeX made readable as plain text: \\frac{a}{b} -> (a)/(b), \\times -> ×, ..."""
    for code, symbol in ((r"\times", "×"), (r"\div", "÷"), (r"\pm", "±"), (r"\pi", "π"),
                         (r"\sqrt", "√"), (r"\theta", "θ"), (r"\cdot", "·"), (r"\leq", "≤"),
                         (r"\geq", "≥"), (r"\neq", "≠"), (r"\frac", "")):
        maths = maths.replace(code, symbol)
    maths = re.sub(r"\}\s*\{", ")/(", maths)   # the gap between a fraction's top and bottom
    return re.sub(r"\\[a-zA-Z]+", "", maths).replace("{", "(").replace("}", ")")


def _draw(text: str, colour: QColor, size: float, scale: float, as_maths: bool) -> QImage:
    figure = Figure(dpi=100 * scale)
    FigureCanvasAgg(figure)   # gives the figure something to draw on
    figure.text(0, 0, text, fontsize=size, color=colour.name(), parse_math=as_maths)
    data = BytesIO()
    figure.savefig(data, format="png", transparent=True, bbox_inches="tight", pad_inches=0.06)
    image = QImage.fromData(data.getvalue(), "PNG")
    if image.isNull():
        raise ValueError("matplotlib made an empty picture")
    return image


if __name__ == "__main__":
    from PySide6.QtGui import QGuiApplication

    from paths import DATA_DIR

    app = QGuiApplication([])
    sample = picture(r"x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}", QColor(190, 245, 255), scale=2)
    out = DATA_DIR / "maths_test.png"
    sample.save(str(out))
    print(f"Saved {out} ({sample.width()} x {sample.height()} pixels)")
    broken = picture(r"\frac{oops", QColor(190, 245, 255))
    print(f"Broken LaTeX still drew something: {not broken.isNull()}")
