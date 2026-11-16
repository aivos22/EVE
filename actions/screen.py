"""
look_at_screen: E.V.E. takes a picture of your screen and reads it, for
"what's this question asking?", "summarise this page" or "what's wrong
with this code?".

How it works:
  1. Windows tells us which monitor the HUD window is on (if you have more
     than one, that's the one she looks at).
  2. mss takes a screenshot of just that monitor, straight into memory.
  3. Pillow shrinks it (at most MAX_WIDTH wide) and turns it into a JPEG,
     still in memory: a few hundred KB instead of ~15 MB.
  4. The tool hands the picture back to the brain, which sends it to
     Gemini next to sir's question (see _text_pieces in brain/gemini_brain.py).

Privacy rules:
  - the picture is NEVER written to disk; it only lives in memory for the
    one question, and is gone once she's answered
  - it's left out of the diary; the diary just says
    "[ACTION] Looked at screen (monitor 1 of 1, 1920x804, 210 KB, not saved)"
  - it only runs when sir asks: asked_to_look() checks his own words, in
    our code, so Gemini can't decide to look by itself

The HUD sits on top of the screen, so it's in the picture too, unless
"hide_hud_from_screenshots" is true in data/actions.json. Windows then
leaves the HUD out of ALL screen captures, including your own screenshots
and recordings. It's read when E.V.E. starts.

Test it alone (takes a picture and throws it away; no Gemini):
    .venv\\Scripts\\python -m actions screen
"""

import ctypes
import io
import logging
import re
from ctypes import wintypes

from actions import settings

MAX_WIDTH = 1920     # pixels. Smaller = smaller upload, but small text gets hard to read
JPEG_QUALITY = 75    # 0-100

diary = logging.getLogger("eve")
_hud_window = None   # the HUD's window ID, given by main.py (None when testing alone)

# Words that mean sir is asking about his screen. His own message must
# contain one of these, or the tool refuses to look.
ASKING_WORDS = re.compile(
    r"\b(screens?|monitors?|display|look(ing)?|see|seeing|read(ing)?|showing|in front of me|on here)\b"
    r"|\bth(is|ese|at) (question|page|code|error|email|message|text|essay|article|tab|window|website|"
    r"site|document|doc|picture|image|photo|graph|chart|diagram|equation|sum|problem|bit|line|"
    r"paragraph|word|sentence|function|table|slide|form|map|game|video)s?\b",
    re.IGNORECASE)


def asked_to_look(text: str) -> bool:
    """True if sir's message is about something on his screen."""
    return bool(ASKING_WORDS.search(text or ""))


# --- Which monitor --------------------------------------------------------

class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


NEAREST = 2           # MONITOR_DEFAULTTONEAREST: if it's between two, the one it's mostly on
HIDE_FROM_CAPTURE = 0x11   # WDA_EXCLUDEFROMCAPTURE (Windows 10, 2020 onwards)


def use_window(window_id: int) -> None:
    """
    Called by main.py with the HUD's window ID, so we look at the monitor
    the HUD is on. Also applies "hide_hud_from_screenshots". Runs on the
    main thread, which is the thread Windows wants for that.
    """
    global _hud_window
    _hud_window = window_id
    try:
        hide = settings.load()["screen"]["hide_hud_from_screenshots"]
    except settings.SettingsError:
        hide = False
    if hide and not ctypes.windll.user32.SetWindowDisplayAffinity(wintypes.HWND(window_id), HIDE_FROM_CAPTURE):
        diary.warning("Couldn't hide the HUD from screenshots (needs Windows 10 2004 or newer)")


def _monitor_rect() -> dict:
    """The screen area of the HUD's monitor (or, testing alone, the mouse's), in pixels."""
    user32 = ctypes.windll.user32
    if _hud_window:
        monitor = user32.MonitorFromWindow(wintypes.HWND(_hud_window), NEAREST)
    else:
        point = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        monitor = user32.MonitorFromPoint(point, NEAREST)
    info = _MonitorInfo()
    info.cbSize = ctypes.sizeof(_MonitorInfo)
    if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return {}
    r = info.rcMonitor
    return {"left": r.left, "top": r.top, "width": r.right - r.left, "height": r.bottom - r.top}


# --- Taking the picture ---------------------------------------------------

def capture() -> tuple[bytes, dict]:
    """
    Screenshot the HUD's monitor, shrink it, and return (JPEG bytes, details).
    Nothing touches the disk.
    """
    import mss
    from PIL import Image

    make = getattr(mss, "MSS", None) or mss.mss   # (newer mss renamed it)
    with make() as grabber:
        monitors = grabber.monitors[1:]           # [0] is "all monitors joined together"
        area = _monitor_rect()
        if not area or area["width"] <= 0:
            area = next((m for m in monitors if m.get("is_primary")), monitors[0])
        number = next((i for i, m in enumerate(monitors, start=1)
                       if (m["left"], m["top"]) == (area["left"], area["top"])), 1)
        shot = grabber.grab({k: area[k] for k in ("left", "top", "width", "height")})
        picture = Image.frombytes("RGB", shot.size, shot.rgb)
    del shot

    if picture.width > MAX_WIDTH:
        height = round(picture.height * MAX_WIDTH / picture.width)
        picture = picture.resize((MAX_WIDTH, height), Image.LANCZOS)
    memory = io.BytesIO()   # a "file" that lives in memory only
    picture.save(memory, format="JPEG", quality=JPEG_QUALITY)
    data = memory.getvalue()
    details = {"monitor": f"{number} of {len(monitors)}",
               "size": f"{picture.width}x{picture.height}", "kb": round(len(data) / 1024)}
    picture.close()
    return data, details


# --- The tool Gemini can use ----------------------------------------------

def look_at_screen(question: str) -> dict:
    """
    Take a picture of sir's screen and look at it. Use it ONLY when sir asks
    you to look at, read or explain something on his screen, e.g. "what's
    this question asking?", "summarise this page", "what's wrong with this
    code?", "what am I looking at?". Never use it for anything else. The
    picture comes back with the result: answer sir's question from it,
    briefly and out loud, as usual. If text is too small or unclear, say so.

    Args:
        question: What sir wants to know about his screen, in his words.
    """
    try:
        data, details = capture()
    except Exception as error:   # no screen access, locked PC, odd monitor setup...
        diary.warning(f"Screenshot failed: {error!r}")
        return {"error": f"couldn't take a screenshot: {type(error).__name__}: {error}"[:200],
                "say": "I couldn't get a look at your screen, sir. The log has the details."}
    diary.info(f"[ACTION] Looked at screen (monitor {details['monitor']}, {details['size']}, "
                f"{details['kb']} KB, not saved)")
    # Keys starting with "_" are for the brain only: run_tool leaves them out
    # of the diary, and the brain takes the picture out before sending the
    # rest of the result as text.
    return {"looked": "The screenshot of sir's screen is attached below.", "question": question,
            **details, "_image": data}


REFUSED = {"error": "sir didn't ask you to look at his screen",
           "say": "I only look at your screen when you ask me to, sir. Just say \"look at my screen\"."}
