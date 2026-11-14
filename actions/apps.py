"""
The open_app tool: opens an app, but ONLY one listed in data/actions.json.

The name Gemini sends ("spotify", "vs code") is only used to find an entry
in that file (see actions/settings.py). What actually runs is the "open"
text YOU wrote there, never anything Gemini made up. Nothing is run
through a command prompt, and no extra words are ever passed to the app.

How each kind of "open" is launched:
    "spotify:"              Windows' list of link types says which app owns
                            it; os.startfile hands the link to that app
    "notepad"               found on this PC by name (like typing it in Run)
    "start menu: Discord"   the Start Menu shortcut with that name, or, for
                            apps from the Microsoft Store, the Start Menu's
                            own list of apps

os.startfile is the same as double-clicking something in File Explorer.

Test it alone:   .venv\\Scripts\\python -m actions open_app spotify
"""

import json
import os
import re
import shutil
import subprocess
import winreg
from pathlib import Path

from actions import settings

START_MENU_PREFIX = "start menu:"
# Where Windows keeps Start Menu shortcuts: one folder for everyone, one just for you.
START_MENU_FOLDERS = [
    Path(os.getenv("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
    Path(os.getenv("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
]
# A link type is letters (and - + .) then a colon, like "spotify:" or "ms-settings:".
# "C:\..." isn't one: a single letter then :\ is a drive.
LINK = re.compile(r"^[a-z][a-z0-9+.\-]+:", re.IGNORECASE)


class NotFound(Exception):
    """The app is on the list, but this PC can't find it."""


def open_app(name: str) -> dict:
    """
    Open an app on sir's PC, such as Spotify, Notepad, VS Code or Discord.
    Use it when sir asks you to open, launch or start an app or program.
    You can only open apps set up in sir's list; if the result says an app
    isn't set up, tell him briefly, including which file to add it to.
    Don't use this for websites: use open_website for those.

    Args:
        name: The app's name as sir said it, e.g. "spotify" or "vs code".
    """
    try:
        friendly, entry = settings.find("apps", name)
    except settings.SettingsError as error:
        return {"error": str(error)}
    if friendly is None:
        return {
            "error": f"{name} isn't set up",
            "tell_sir": f"Add {name} to data/actions.json to let me open it.",
            "apps_i_can_open": settings.known_names("apps"),
        }
    try:
        launch(entry["open"])
    except NotFound as problem:
        return {"error": f"{friendly} is on the list but wasn't found on this PC: {problem}",
                "tell_sir": "Check it's installed, or fix its 'open' line in data/actions.json."}
    except OSError as error:   # Windows refused, e.g. the shortcut is broken
        return {"error": f"Windows couldn't open {friendly}: {error.strerror or error}"}
    return {"opened": friendly}


def launch(how: str) -> None:
    """Open something from the settings file. Raises NotFound if it isn't on this PC."""
    how = how.strip()
    if how.lower().startswith(START_MENU_PREFIX):
        os.startfile(_start_menu_item(how[len(START_MENU_PREFIX):].strip()))
    elif LINK.match(how):
        scheme = how.split(":", 1)[0]
        if not _link_type_exists(scheme):
            raise NotFound(f"no app on this PC handles {scheme}: links")
        os.startfile(how)
    else:
        os.startfile(_program(how))


def _link_type_exists(scheme: str) -> bool:
    """True if some app has told Windows it handles links like "spotify:"."""
    # This only READS Windows' list (the registry); nothing is changed.
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, scheme))
        return True
    except OSError:
        return False


def _program(name: str) -> str:
    """The full path of a program Windows can find by name, like "notepad"."""
    # 1. On the PATH: the folders Windows searches when you type a command.
    found = shutil.which(name)
    if found:
        return found
    # 2. "App Paths": where installers register names like "chrome" or "winword".
    exe = name if name.lower().endswith(".exe") else f"{name}.exe"
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}") as key:
                path = winreg.QueryValue(key, None)
                if path and Path(path.strip('"')).exists():
                    return path.strip('"')
        except OSError:
            pass
    raise NotFound(f"no program called {name}")


def _start_menu_item(name: str) -> str:
    """A Start Menu shortcut (or Store app) with this name, ready for os.startfile."""
    wanted = settings.simplify(name)
    for folder in START_MENU_FOLDERS:
        if folder.is_dir():
            for shortcut in folder.rglob("*.lnk"):
                if settings.simplify(shortcut.stem) == wanted:
                    return str(shortcut)
    # Apps from the Microsoft Store have no shortcut file. The Start Menu's
    # own list has them, with an ID that "shell:AppsFolder" can open.
    for app in _start_menu_apps():
        if settings.simplify(app.get("Name", "")) == wanted and app.get("AppID"):
            return f"shell:AppsFolder\\{app['AppID']}"
    raise NotFound(f"no Start Menu item called {name}")


def _start_menu_apps() -> list[dict]:
    """Every app in the Start Menu, as [{"Name": ..., "AppID": ...}]."""
    # A fixed PowerShell command that only LISTS apps. No outside text is
    # ever added to it. It takes about a second, so it's only a last resort.
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-StartApps | ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW)   # no black window flashing up
        apps = json.loads(result.stdout or "[]")
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    return apps if isinstance(apps, list) else [apps]
