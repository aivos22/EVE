"""
The close_app tool: closes an app, but ONLY one listed in data/actions.json.

How she finds it: each app in the settings file has a "process" line, the
name of its program file, e.g. "Spotify.exe". (Task Manager's Details tab
shows these names.) She looks for windows belonging to that program.

How she closes it: POLITELY. She sends each of its windows the same
message Windows sends when you click the window's X. So:
  - if you have unsaved work, the app still asks "Save changes?" itself
  - apps that go to the tray when you click X (Discord, sometimes Spotify)
    do the same here: their window closes but they keep running
  - she NEVER force-closes ("kills") anything

Never closed, whatever the settings file says: File Explorer (its program
also runs your taskbar and desktop), Task Manager, Windows Settings,
E.V.E. herself, and Windows' own background programs.

Test it alone:   .venv\\Scripts\\python -m actions close notepad
"""

import ctypes
import logging
import os
import time
from ctypes import wintypes

import psutil

from actions import settings
from actions.apps import SETTINGS_BROKEN

WAIT_SECONDS = 3   # how long to wait for the windows to go before saying it didn't work

# Program files she never closes, in lower case.
NEVER_CLOSE = {
    "explorer.exe", "taskmgr.exe", "systemsettings.exe", "applicationframehost.exe",
    "python.exe", "pythonw.exe", "dwm.exe", "csrss.exe", "winlogon.exe", "lsass.exe",
    "svchost.exe", "services.exe", "wininit.exe", "smss.exe", "sihost.exe", "ctfmon.exe",
    "searchhost.exe", "startmenuexperiencehost.exe", "shellexperiencehost.exe", "textinputhost.exe",
}

diary = logging.getLogger("eve")

# --- Windows' own functions (user32.dll), used through ctypes -----------------
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_WINDOW_FOUND = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
_user32.EnumWindows.argtypes = [_WINDOW_FOUND, wintypes.LPARAM]
_user32.EnumChildWindows.argtypes = [wintypes.HWND, _WINDOW_FOUND, wintypes.LPARAM]
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
_user32.GetWindow.restype = wintypes.HWND
_user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.IsWindow.argtypes = [wintypes.HWND]
_user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

WM_CLOSE = 0x0010          # "please close": the same as clicking the X
GW_OWNER = 4
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x80    # little helper windows that aren't in the taskbar
# Apps from the Microsoft Store (Calculator, for one) sit inside a frame
# window that belongs to ApplicationFrameHost.exe, not to the app itself.
STORE_APP_FRAME = "ApplicationFrameWindow"


def close_app(name: str) -> dict:
    """
    Close an app on sir's PC, such as Spotify, Notepad or Discord, the same
    way as clicking its X. Use it when sir asks you to close, quit or exit
    an app or program. You can only close apps set up in sir's list. If the
    app has unsaved work, it will ask sir itself; never say it was saved.

    Args:
        name: The app's name as sir said it, e.g. "spotify" or "vs code".
    """
    try:
        friendly, entry = settings.find("apps", name)
    except settings.SettingsError as error:
        return {"error": str(error), "say": SETTINGS_BROKEN}
    if friendly is None:
        return {"error": f"{name} isn't set up",
                "apps_i_can_close": settings.known_names("apps"),
                "say": f"I don't have {name} on my list, sir, so I can't close it."}

    programs = {p.lower() for p in entry.get("process", [])}
    if programs & NEVER_CLOSE:
        return {"error": f"{friendly} is never closed by E.V.E.",
                "say": f"I'd rather not close {friendly}, sir. "
                       + ("It runs your taskbar too." if "explorer.exe" in programs else
                          "That one's best closed by hand.")}
    if not programs:
        return {"error": f"{friendly} has no 'process' line in data/actions.json",
                "say": f"I don't know which program {friendly} runs as, sir. You can add a process "
                       "line for it in the actions file in my data folder."}

    running = _running(programs)
    if not running:
        return {"not_running": friendly, "say": f"{friendly} isn't open, sir."}
    windows = _windows_of(running)
    if not windows:
        return {"no_window": friendly,
                "say": f"{friendly} is running in the background with no window open, sir, "
                       "so there's nothing for me to close."}

    refused = [hwnd for hwnd in windows if not _user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)]
    if len(refused) == len(windows):
        # Usually an app running as administrator: Windows won't let a
        # normal program send it messages.
        return {"error": f"Windows refused to pass the close message to {friendly}",
                "say": f"Windows wouldn't let me close {friendly}, sir. "
                       "It may be running as administrator."}

    left = _wait_until_gone(windows)
    diary.info(f"[ACTION] Asked {friendly} to close ({len(windows)} window(s)); "
               f"{len(left)} still open after {WAIT_SECONDS}s")
    if left:
        return {"asked_to_close": friendly, "still_open": len(left),
                "say": f"I've asked {friendly} to close, sir, but it's still open. "
                       "It may be asking you something, like whether to save."}
    return {"closed": friendly, "say": f"Closed {friendly}, sir."}


def _running(programs: set[str]) -> set[int]:
    """The process IDs of every running copy of these programs (never E.V.E.'s own)."""
    mine = {os.getpid()}
    try:
        mine |= {child.pid for child in psutil.Process().children(recursive=True)}
    except psutil.Error:
        pass
    found = set()
    for proc in psutil.process_iter(["name"]):
        name = (proc.info.get("name") or "").lower()
        if name in programs and proc.pid not in mine:
            found.add(proc.pid)
    return found


def _windows_of(pids: set[int]) -> list[int]:
    """The app's main windows: visible, in the taskbar, belonging to these processes."""
    found = []

    def check(hwnd, _):
        if not _user32.IsWindowVisible(hwnd) or _user32.GetWindow(hwnd, GW_OWNER):
            return True   # hidden, or a dialog that belongs to another window
        if _user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
            return True
        if _pid_of(hwnd) in pids or (_class_of(hwnd) == STORE_APP_FRAME and _store_app_inside(hwnd, pids)):
            found.append(hwnd)
        return True   # True = keep going through the windows

    _user32.EnumWindows(_WINDOW_FOUND(check), 0)
    return found


def _store_app_inside(frame: int, pids: set[int]) -> bool:
    """True if this Store-app frame holds a window from one of these processes."""
    inside = []

    def check(hwnd, _):
        if _pid_of(hwnd) in pids:
            inside.append(hwnd)
            return False   # found it: stop looking
        return True

    _user32.EnumChildWindows(frame, _WINDOW_FOUND(check), 0)
    return bool(inside)


def _pid_of(hwnd) -> int:
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _class_of(hwnd) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def _wait_until_gone(windows: list[int]) -> list[int]:
    """Wait up to WAIT_SECONDS for the windows to close. Returns any still showing."""
    deadline = time.monotonic() + WAIT_SECONDS
    while True:
        left = [hwnd for hwnd in windows if _user32.IsWindow(hwnd) and _user32.IsWindowVisible(hwnd)]
        if not left or time.monotonic() > deadline:
            return left
        time.sleep(0.2)
