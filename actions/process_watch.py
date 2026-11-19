"""
Learning which program an app runs as, by watching it open.

close_app needs each app's program file name ("process" in data/actions.json,
e.g. "Discord.exe"). Reading the shortcut doesn't always tell you: Discord's
shortcut runs Update.exe, games often start through a launcher, and Store
apps have no shortcut at all. So whenever open_app opens something whose
program isn't known yet, E.V.E. watches for a little while:

  1. just before opening it, note every window already on screen
  2. after opening it, look twice a second for NEW windows (up to WATCH_SECONDS)
  3. a new window from a program that has just started is the app: note its
     program name, wait a few more seconds (a splash screen is often
     followed by the real window), and save them all to the app's process line

If the app was already open (so no new window appears), she checks whether
the window that came to the front belongs to a program named like the app
("Spotify" -> Spotify.exe).

It all happens in the background, so she answers "Opening Discord, sir"
straight away. It only ever READS what's on screen; nothing is changed.

Test it:  .venv\\Scripts\\python -m actions.process_watch notepad
(opens the app the normal way and prints what it learnt)
"""

import logging
import os
import threading
import time
from ctypes import wintypes

import psutil

from actions import settings
from actions.close import (GW_OWNER, GWL_EXSTYLE, NEVER_CLOSE, STORE_APP_FRAME, WS_EX_TOOLWINDOW,
                           _WINDOW_FOUND, _class_of, _pid_of, _user32)

WATCH_SECONDS = 20    # how long to wait for the app's window
SETTLE_SECONDS = 4    # after the first window, how long to keep watching for the real one
NOT_THE_APP = NEVER_CLOSE | {
    # Windows' helpers and launchers: they show windows, but they're not the app.
    "conhost.exe", "openconsole.exe", "windowsterminal.exe", "werfault.exe", "rundll32.exe",
    "openwith.exe", "pickerhost.exe", "consent.exe", "update.exe", "launcher.exe",
    "cmd.exe", "powershell.exe", "pwsh.exe", "lockapp.exe", "useroobebroker.exe",
}

diary = logging.getLogger("eve")


def _taskbar_windows() -> dict[int, int]:
    """Every main window on screen, as {window: process ID}. Store apps give their own process."""
    found = {}

    def check(hwnd, _):
        if not _user32.IsWindowVisible(hwnd) or _user32.GetWindow(hwnd, GW_OWNER):
            return True
        if _user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
            return True
        pid = _pid_of(hwnd)
        if _class_of(hwnd) == STORE_APP_FRAME:   # a Store app: the real app is inside the frame
            pid = _store_app_pid(hwnd, pid)
        found[hwnd] = pid
        return True

    _user32.EnumWindows(_WINDOW_FOUND(check), 0)
    return found


def _store_app_pid(frame: int, frame_pid: int) -> int:
    inner = []

    def check(hwnd, _):
        pid = _pid_of(hwnd)
        if pid != frame_pid:
            inner.append(pid)
            return False
        return True

    _user32.EnumChildWindows(frame, _WINDOW_FOUND(check), 0)
    return inner[0] if inner else frame_pid


def _mine() -> set[int]:
    """E.V.E.'s own processes, never to be mistaken for the app."""
    mine = {os.getpid()}
    try:
        mine |= {child.pid for child in psutil.Process().children(recursive=True)}
    except psutil.Error:
        pass
    return mine


class ProcessWatch:
    """Make one just BEFORE opening the app, then call start() once it has opened."""

    def __init__(self, friendly: str):
        self.friendly = friendly
        self.before = set(_taskbar_windows())
        self.started = time.time()
        self.learnt: list[str] = []   # filled in when it's done (for testing)
        self.done = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._watch, name="learn-process", daemon=True).start()

    def _watch(self) -> None:
        try:
            programs = self._look()
            if programs:
                self.learnt = settings.add_processes(self.friendly, programs)
                if self.learnt:
                    diary.info(f"[ACTION] Learnt that {self.friendly} runs as "
                               f"{', '.join(self.learnt)} (saved, so I can close it)")
        except Exception:
            diary.warning(f"Couldn't work out which program {self.friendly} runs as", exc_info=True)
        finally:
            self.done.set()

    def _look(self) -> list[str]:
        mine = _mine()
        words = [w for w in settings.simplify_words(self.friendly) if len(w) >= 3]
        programs: list[str] = []
        deadline = time.monotonic() + WATCH_SECONDS
        while time.monotonic() < deadline:
            time.sleep(0.5)
            for hwnd, pid in _taskbar_windows().items():
                if hwnd in self.before or pid in mine:
                    continue
                name = self._program(pid, must_be_new=True)
                if name and name not in programs:
                    programs.append(name)
                    deadline = min(deadline, time.monotonic() + SETTLE_SECONDS)
            if not programs:
                # Already open? Then the window just came to the front instead.
                front = _user32.GetForegroundWindow()
                name = self._program(_taskbar_windows().get(front, 0), must_be_new=False) if front else None
                if name and any(word in settings.simplify(name) for word in words):
                    return [name]
        return programs

    def _program(self, pid: int, must_be_new: bool) -> str | None:
        """The program file name of a process (None if it's not the app's)."""
        if not pid:
            return None
        try:
            proc = psutil.Process(pid)
            name = proc.name()
            if must_be_new and proc.create_time() < self.started - 2:
                return None   # was already running before she opened the app
        except psutil.Error:
            return None
        if not name.lower().endswith(".exe") or name.lower() in NOT_THE_APP:
            return None
        return name


_user32.GetForegroundWindow.restype = wintypes.HWND


if __name__ == "__main__":
    import sys

    from actions.apps import open_app

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    wanted = " ".join(sys.argv[1:]) or "notepad"
    print(open_app(wanted))
    print("Watching for its window...")
    for thread in threading.enumerate():
        if thread.name == "learn-process":
            thread.join()
    friendly, entry = settings.find("apps", wanted)
    print(f"{friendly}: process = {entry and entry.get('process')}")
