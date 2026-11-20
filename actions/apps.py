"""
The open_app tool: opens any app installed on sir's PC.

Where she looks, in order:
  1. Sir's own list, data/actions.json (see actions/settings.py). The name
     Gemini sends ("spotify", "fortnight") is only used to find an entry;
     what runs is the "open" text written there.
  2. The Start Menu: every app installed the normal way has an entry there,
     including Microsoft Store apps and games. She finds the closest name
     ("word" -> Word, "photoshop" -> Adobe Photoshop 2025) and opens it the
     same way as clicking it in the Start Menu. If several fit ("python"),
     she asks which one. Uninstallers, manuals, "on the web" links and
     similar clutter are never picked.
     An app she opens this way is then saved in data/actions.json by
     herself, so next time it's instant, and close_app can close it.

Safety: she can only open what's already in the Start Menu or sir's list.
Nothing is run through a command prompt, no extra words are ever passed to
the app, and she never runs a file from some random folder.

How each kind of "open" in the settings file is launched:
    "spotify:"              Windows' list of link types says which app owns
                            it; os.startfile hands the link to that app
    "notepad"               found on this PC by name (like typing it in Run)
    "start menu: Discord"   the Start Menu shortcut with that name, or, for
                            apps from the Microsoft Store, the Start Menu's
                            own list of apps

os.startfile is the same as double-clicking something in File Explorer.

Test it alone:   .venv\\Scripts\\python -m actions open_app spotify
See what a name would match, without opening anything:
                 .venv\\Scripts\\python -m actions.apps find photoshop
"""

import difflib
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import winreg
from pathlib import Path

from actions import settings

diary = logging.getLogger("eve")

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
    Open any app or game installed on sir's PC, such as Spotify, Word,
    Photoshop, Steam or Valorant. Use it when sir asks you to open, launch,
    start or play an app, program or game. It searches his Start Menu, so
    try it for anything he names. If the result has "choices", ask sir which
    one he meant (the result's "say" line does this), and when he answers,
    call this again with the exact name he picked.
    Don't use this for websites: use open_website for those.

    Args:
        name: The app's name as sir said it, e.g. "spotify" or "vs code".
              When sir picks one of the choices, use that exact name.
    """
    # Each result has a "say" line: what she says straight away, without
    # asking Gemini to word it (one request saved; see actions/__init__.py).
    try:
        friendly, entry = settings.find("apps", name)
    except settings.SettingsError as error:
        return {"error": str(error), "say": SETTINGS_BROKEN}
    if friendly is None:
        return _open_from_start_menu(name)
    watch = _watch_for(friendly, entry)
    try:
        launch(entry["open"])
    except NotFound as problem:
        return {"error": f"{friendly} is on the list but wasn't found on this PC: {problem}",
                "tell_sir": "Check it's installed, or fix its 'open' line in data/actions.json.",
                "say": f"{friendly} is on my list, sir, but I can't find it on this PC."}
    except OSError as error:   # Windows refused, e.g. the shortcut is broken
        return {"error": f"Windows couldn't open {friendly}: {error.strerror or error}",
                "say": f"Windows wouldn't open {friendly} for me, sir."}
    if watch:
        watch.start()
    return {"opened": friendly, "say": f"Opening {friendly}, sir."}


def _watch_for(friendly: str, entry: dict | None):
    """
    If we don't know for sure which program this app runs as, start
    watching (BEFORE it opens) so she can learn it: see actions/process_watch.py.
    Apps she added herself are always watched, as a shortcut can point to a launcher.
    """
    if entry and entry.get("process") and entry.get("added_by") != "E.V.E.":
        return None   # sir's own process line: nothing to learn
    from actions.process_watch import ProcessWatch   # (here, as it uses close.py, which uses this file)
    try:
        return ProcessWatch(friendly)
    except Exception:
        diary.warning(f"Couldn't start watching {friendly} open", exc_info=True)
        return None


# Said when data/actions.json can't be read. (The exact reason goes in the diary.)
SETTINGS_BROKEN = "My actions file has a mistake in it, sir. The log has the details."


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
    for fresh in (False, True):   # if it's not there, look again: it may be newly installed
        for item in start_menu(refresh=fresh):
            if item.key == wanted:
                return item.target
    raise NotFound(f"no Start Menu item called {name}")


# --- The Start Menu -------------------------------------------------------

class StartMenuItem:
    """One app in the Start Menu: its name, and what os.startfile opens."""

    def __init__(self, name: str, target: str, shortcut: Path | None = None):
        self.name = name            # as the Start Menu shows it, e.g. "Adobe Photoshop 2025"
        self.target = target        # a .lnk file, or "shell:AppsFolder\<ID>" for Store apps
        self.shortcut = shortcut    # the .lnk file, if it has one (for finding its program)
        self.key = settings.simplify(name)
        self.words = _words(name)


# Start Menu entries that aren't really apps, so she never picks them:
# uninstallers, manuals, links to websites, bug reporters...
CLUTTER = re.compile(
    r"\b(uninstall\w*|documentation|docs|manuals?|readme|read me|release notes|faqs?|"
    r"on the web|website|help|support center|report a problem|error reporter|"
    r"updater|telemetry|troubleshooter|config file|licen[cs]e)\b", re.IGNORECASE)

# Words a name can have extra without it being a different app: "photoshop"
# still means "Adobe Photoshop 2025". (Years and bits in brackets, too.)
EXTRA_WORDS = {"microsoft", "google", "adobe", "windows", "app", "the", "maxon", "razer",
               "nvidia", "steelseries", "launcher", "desktop", "classic", "new", "64bit", "x64"}

REFRESH_AFTER = 10 * 60      # read the Start Menu again if the list is older than this (seconds)
_menu: list[StartMenuItem] = []
_menu_time = 0.0
_menu_lock = threading.Lock()


def _words(name: str) -> list[str]:
    """ "Adobe Photoshop 2025" -> ["adobe", "photoshop", "2025"] """
    return [w for w in (settings.simplify(part) for part in re.split(r"[\s\-_.()]+", name)) if w]


def _is_extra(word: str) -> bool:
    return word in EXTRA_WORDS or word.isdigit()


def start_menu(refresh: bool = False) -> list[StartMenuItem]:
    """
    Every app in the Start Menu (clutter left out). Read once and kept in
    memory, because the Store-app part takes about a second.
    """
    global _menu, _menu_time
    with _menu_lock:
        if refresh or not _menu or time.time() - _menu_time > REFRESH_AFTER:
            _menu = _read_start_menu()
            _menu_time = time.time()
        return _menu


def _read_start_menu() -> list[StartMenuItem]:
    items, seen = [], set()

    def add(item: StartMenuItem) -> None:
        # Skip clutter, and the same name twice (Windows lists some apps twice).
        if item.key and item.key not in seen and not CLUTTER.search(item.name):
            seen.add(item.key)
            items.append(item)

    # 1. Shortcut files: the normal kind of installed app.
    for folder in START_MENU_FOLDERS:
        if folder.is_dir():
            for shortcut in folder.rglob("*.lnk"):
                add(StartMenuItem(shortcut.stem, str(shortcut), shortcut))
    # 2. Apps from the Microsoft Store (and many games) have no shortcut file.
    #    The Start Menu's own list has them, with an ID that "shell:AppsFolder" opens.
    for app in _start_menu_apps():
        name, app_id = app.get("Name"), app.get("AppID")
        if isinstance(name, str) and isinstance(app_id, str) and app_id:
            add(StartMenuItem(name, f"shell:AppsFolder\\{app_id}"))
    return items


def _start_menu_apps() -> list[dict]:
    """Every app in the Start Menu, as [{"Name": ..., "AppID": ...}]."""
    # A fixed PowerShell command that only LISTS apps. No outside text is
    # ever added to it. UTF-8, so names like "HWiNFO® 64" come through intact.
    command = "[Console]::OutputEncoding = [Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json -Compress"
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True, encoding="utf-8", errors="replace", timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW)   # no black window flashing up
        apps = json.loads(result.stdout or "[]")
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    return apps if isinstance(apps, list) else [apps]


def _score(wanted: str, item: StartMenuItem) -> int:
    """
    How well a name sir said fits a Start Menu app, 0 (not at all) to 100.
        100  the same name               "word" -> Word
         90  same, plus brand/year words "photoshop" -> Adobe Photoshop 2025
     80-5n   his word, plus n others     "premiere" -> Adobe Premiere Pro 2025 (75)
     75-80   2+ of his words, plus others "rainbow six" -> Tom Clancy's Rainbow Six Siege
         70  nearly the same spelling    "valorent" -> VALORANT
    """
    key = settings.simplify(wanted)
    if not key:
        return 0
    if key == item.key:
        return 100
    said = [w for w in _words(wanted) if not _is_extra(w)] or _words(wanted)
    if said and all(w in item.words for w in said):
        others = [w for w in item.words if w not in said]
        unusual = [w for w in others if not _is_extra(w)]
        if not unusual:
            return 90
        if len(said) >= 2:
            # Two or more of his words all fit ("rainbow six"): a strong sign,
            # whatever else the name has (Tom Clancy's Rainbow Six Siege).
            return max(75, 80 - 2 * len(unusual))
        return max(40, 80 - 5 * len(unusual))
    # Close spelling (Whisper mishearing, or a typo). Compared without brand
    # words too, so "photoshoop" still finds "Adobe Photoshop 2025".
    plain = "".join(w for w in item.words if not _is_extra(w)) or item.key
    closeness = max(difflib.SequenceMatcher(None, key, item.key).ratio(),
                    difflib.SequenceMatcher(None, key, plain).ratio())
    return 70 if closeness >= 0.85 else 0


def search(name: str) -> list[tuple[int, StartMenuItem]]:
    """The Start Menu apps that fit `name`, best first, as (score, item)."""
    for fresh in (False, True):   # nothing found: read the Start Menu again (new install?)
        found = [(_score(name, item), item) for item in start_menu(refresh=fresh)]
        found = sorted(((s, i) for s, i in found if s >= 60), key=lambda pair: (-pair[0], len(pair[1].name)))
        if found:
            return found
    return []


def decide(found: list[tuple[int, StartMenuItem]]):
    """
    Open the best match straight away, or ask? Returns (sure, best, rivals).
    Sure = the exact name, or a good match with nothing else close to it.
    Rivals = other apps that fit nearly as well (within 10 points).
    """
    best_score, best = found[0]
    rivals = [item for score, item in found[1:] if score >= best_score - 10]
    sure = best_score == 100 or (not rivals and best_score >= 75)
    return sure, best, rivals


def _open_from_start_menu(name: str) -> dict:
    """Not in sir's list: find it in the Start Menu, open it, and remember it."""
    found = search(name)
    if not found:
        return {"error": f"no app called {name} on this PC",
                "say": f"I couldn't find {name} on this PC, sir."}
    sure, best, rivals = decide(found)
    if not sure:
        choices = [best.name] + [item.name for item in rivals][:2]
        if len(choices) == 1:
            return {"choices": choices, "say": f"Did you mean {choices[0]}, sir?"}
        listed = ", ".join(choices[:-1]) + " or " + choices[-1]
        return {"choices": choices, "say": f"I found a few, sir: {listed}. Which one?"}
    watch = _watch_for(best.name, None)
    try:
        os.startfile(best.target)
    except OSError as error:
        return {"error": f"Windows couldn't open {best.name}: {error.strerror or error}",
                "say": f"Windows wouldn't open {best.name} for me, sir."}
    _remember(best, name)
    if watch:
        watch.start()   # (after _remember, so the app is in the file to add its program to)
    return {"opened": best.name, "say": f"Opening {best.name}, sir."}


# --- Remembering apps she found -------------------------------------------

# Programs a shortcut can point to that only START the real app, so they're
# no use for closing it (Discord's shortcut runs Update.exe, for one).
LAUNCHERS = {"update.exe", "launcher.exe", "explorer.exe", "cmd.exe", "powershell.exe", "pwsh.exe"}


def _remember(item: StartMenuItem, said: str) -> None:
    """
    Save an app she found in the Start Menu to data/actions.json, so next
    time it's instant, and close_app knows its program file. If anything
    goes wrong here it doesn't matter: the app is already open.
    """
    try:
        entry = {"names": [said.strip()] if settings.simplify(said) != item.key else [],
                 "open": f"{START_MENU_PREFIX} {item.name}",
                 "process": [program] if (program := _program_of(item)) else [],
                 "added_by": "E.V.E."}
        if settings.add_app(item.name, entry):
            diary.info(f"[ACTION] Saved {item.name} to data/actions.json "
                       f"(process: {', '.join(entry['process']) or 'unknown'})")
    except Exception:
        diary.warning(f"Couldn't save {item.name} to data/actions.json", exc_info=True)


def _program_of(item: StartMenuItem) -> str | None:
    """The program file a Start Menu shortcut runs, e.g. "Photoshop.exe" (None if unknown)."""
    if item.shortcut is None:
        return None   # Store apps have no shortcut file to read
    import comtypes
    import comtypes.client
    comtypes.CoInitialize()   # needed once on each background thread that uses Windows' COM
    try:
        # WScript.Shell is Windows' own shortcut reader. This only READS the shortcut.
        # (dynamic=True: WScript.Shell is a "script" object, reached by name, not a fixed layout.)
        shell = comtypes.client.CreateObject("WScript.Shell", dynamic=True)
        target = shell.CreateShortcut(str(item.shortcut)).TargetPath
    except Exception:
        return None
    finally:
        comtypes.CoUninitialize()
    program = Path(target or "").name
    if program.lower().endswith(".exe") and program.lower() not in LAUNCHERS:
        return program
    return None


if __name__ == "__main__":
    # .venv\Scripts\python -m actions.apps find photoshop   (shows matches, opens nothing)
    # .venv\Scripts\python -m actions.apps list             (every app she can see)
    import sys
    words = sys.argv[1:]
    if words[:1] == ["list"]:
        apps = start_menu()
        for app in apps:
            print(f"  {app.name}")
        print(f"\n{len(apps)} apps")
    elif words[:1] == ["find"] and words[1:]:
        wanted = " ".join(words[1:])
        for score, app in search(wanted)[:8]:
            print(f"  {score:>3}  {app.name}")
        found = search(wanted)
        if not found:
            print("\nWhat she'd do: say she couldn't find it")
        else:
            sure, best, rivals = decide(found)
            print(f"\nWhat she'd do: open {best.name}" if sure else
                  f"\nWhat she'd do: ask which one ({', '.join([best.name] + [r.name for r in rivals][:2])})")
    else:
        print("Use:  python -m actions.apps find <name>   or   python -m actions.apps list")
