"""
Action settings: the apps and websites E.V.E. is allowed to open.

They live in data/actions.json, a plain text file you can edit yourself.
If it's missing, it's created with the defaults below the first time it's
needed. It's read fresh every time an action runs, so your changes work
straight away, with no restart.

This is an ALLOWLIST: E.V.E. can only open what's written in this file.
Whatever name Gemini passes is only used to LOOK UP an entry here; it's
never run as a command itself.

Each app has a friendly name, a few other names you might call it, and how
to open it. Three ways work on any PC, without knowing where it's installed:

    "spotify:"              a web-style link (a "URI") that Windows hands to
                            whichever program owns it (Spotify, Settings...)
    "notepad"               a program Windows can find by name (on the PATH)
    "start menu: Discord"   the Start Menu shortcut with that name

Each website has its address, and optionally a "search" address where {}
is replaced by what to search for.

Each folder is one she may look inside (find, list and open files), with
its full path. Everything inside it, including subfolders, is allowed;
nothing outside it is. Paths may use ~ for your user folder.

"screen" has the switches for look_at_screen (actions/screen.py).

If your file is from before a section existed, that section is added to
it with the defaults, and everything you wrote is kept.

See what's set up:   .venv\\Scripts\\python -m actions.settings
"""

import ctypes
import json
import os
import re
import uuid
from pathlib import Path

from paths import DATA_DIR

SETTINGS_FILE = DATA_DIR / "actions.json"

# Written to data/actions.json the first time. (Changing these later
# doesn't change your file: edit the file itself.)
DEFAULTS = {
    "_how_to": [
        "The apps and websites E.V.E. may open. She can't open anything else.",
        "names = other things you might call it. Capitals and spaces don't matter.",
        "App 'open' can be: a link like 'spotify:', a program name like 'notepad',",
        "or 'start menu: <shortcut name>' to use a Start Menu shortcut.",
        "Website 'search' is optional; {} is replaced by what to search for.",
        "Changes work straight away, no restart needed.",
    ],
    "apps": {
        "Notepad": {"names": ["notes", "text editor"], "open": "notepad"},
        "Calculator": {"names": ["calc"], "open": "calc"},
        "Paint": {"names": ["ms paint"], "open": "mspaint"},
        "File Explorer": {"names": ["explorer", "files", "my files", "file manager"], "open": "explorer"},
        "Task Manager": {"names": [], "open": "taskmgr"},
        "Settings": {"names": ["windows settings", "pc settings"], "open": "ms-settings:"},
        "Spotify": {"names": ["spotify music"], "open": "spotify:"},
        "VS Code": {"names": ["code", "vscode", "visual studio code"], "open": "start menu: Visual Studio Code"},
        "Edge": {"names": ["microsoft edge"], "open": "microsoft-edge:"},
        "Chrome": {"names": ["google chrome"], "open": "start menu: Google Chrome"},
        "Discord": {"names": [], "open": "start menu: Discord"},
    },
    "websites": {
        "YouTube": {"names": ["yt"], "url": "https://www.youtube.com",
                    "search": "https://www.youtube.com/results?search_query={}"},
        "Google": {"names": [], "url": "https://www.google.com",
                   "search": "https://www.google.com/search?q={}"},
        "Gmail": {"names": ["email", "mail", "google mail"], "url": "https://mail.google.com"},
        "GitHub": {"names": [], "url": "https://github.com",
                   "search": "https://github.com/search?q={}"},
        "Wikipedia": {"names": ["wiki"], "url": "https://en.wikipedia.org",
                      "search": "https://en.wikipedia.org/w/index.php?search={}"},
        "BBC News": {"names": ["bbc", "news"], "url": "https://www.bbc.co.uk/news",
                     "search": "https://www.bbc.co.uk/search?q={}"},
        "Netflix": {"names": [], "url": "https://www.netflix.com",
                    "search": "https://www.netflix.com/search?q={}"},
        "Google Maps": {"names": ["maps"], "url": "https://www.google.com/maps",
                        "search": "https://www.google.com/maps/search/{}"},
        "Amazon": {"names": ["amazon uk"], "url": "https://www.amazon.co.uk",
                   "search": "https://www.amazon.co.uk/s?k={}"},
    },
    # "folders" is filled in when the file is written (see _default_folders),
    # because where Documents really is differs between PCs (e.g. OneDrive).
    "screen": {
        "hide_hud_from_screenshots": False,
    },
}

HOW_TO_FOLDERS = [
    "Folders: the only places she may find, list and open files (subfolders too).",
    "Add one like  \"EPQ\": {\"names\": [\"my epq\"], \"path\": \"D:\\\\School\\\\EPQ\"}",
    "(in a path, write each \\ twice, or use / instead).",
    "screen: hide_hud_from_screenshots true = she sees past the HUD, but it's also",
    "missing from YOUR screenshots and recordings. Needs a restart of E.V.E.",
]

HOW_TO_CLOSE = [
    "App 'process' = its program file (Task Manager > Details shows them), so she can",
    "close it, e.g. \"process\": [\"Spotify.exe\"]. No process line = she can't close it.",
    "She closes apps politely, like clicking X, so unsaved work still asks you first.",
]

# The program files of common apps, so "close Spotify" works without you
# having to look them up. Added to apps in your file that have no "process"
# line yet (only for these names; lines you've written are never changed).
# File Explorer, Task Manager and Settings are listed so she knows to say
# she won't close them (see actions/close.py).
KNOWN_PROCESSES = {
    "Notepad": ["Notepad.exe"], "Calculator": ["CalculatorApp.exe"], "Paint": ["mspaint.exe"],
    "File Explorer": ["explorer.exe"], "Task Manager": ["Taskmgr.exe"],
    "Settings": ["SystemSettings.exe"], "Spotify": ["Spotify.exe"], "VS Code": ["Code.exe"],
    "Edge": ["msedge.exe"], "Chrome": ["chrome.exe"], "Discord": ["Discord.exe"],
    "Epic Games": ["EpicGamesLauncher.exe"], "Fortnite": ["FortniteClient-Win64-Shipping.exe"],
    "Minecraft Launcher": ["Minecraft.exe"],
}

# Windows' own IDs for its special folders, so we find them wherever they really are.
KNOWN_FOLDERS = {
    "Documents": ("FDD39AD0-238F-46AF-ADB4-6C85480369C7", ["my documents", "docs"]),
    "Desktop": ("B4BFCC3A-DB2C-424C-B029-7FE99A87C641", []),
    "Downloads": ("374DE290-123F-4565-9164-39C4925E467B", ["my downloads"]),
}


class SettingsError(Exception):
    """data/actions.json couldn't be read. The message says why, in plain words."""


def simplify(name: str) -> str:
    """
    Boil a name down for matching: lower case, letters and numbers only,
    and no "the" in front. "VS Code" -> "vscode", "the Spotify app" -> "spotifyapp"
    """
    name = re.sub(r"^\s*the\s+", "", name.lower())
    return re.sub(r"[^a-z0-9]", "", name)


FILLER_WORDS = {"the", "my", "a", "an", "file", "files", "called", "named", "document", "doc"}


def simplify_words(name: str) -> list[str]:
    """
    "My physics-notes file" -> ["physics", "notes"]: each word simplified,
    without filler words. (If that leaves nothing, the filler words stay.)
    """
    words = [simplify(w) for w in re.split(r"[\s_\-]+", name)]
    words = [w for w in words if w]
    useful = [w for w in words if w not in FILLER_WORDS]
    return useful or words


def load() -> dict:
    """
    Read data/actions.json (creating it with the defaults if it's missing).
    Returns {"apps": {...}, "websites": {...}, "problems": [...]}, where
    problems lists any entries that were skipped because they were filled
    in wrongly, so one typo doesn't switch everything off.
    """
    if not SETTINGS_FILE.exists():
        first = dict(DEFAULTS, _how_to=DEFAULTS["_how_to"] + HOW_TO_FOLDERS + HOW_TO_CLOSE,
                     folders=_default_folders())
        for name, app in first["apps"].items():
            app["process"] = list(KNOWN_PROCESSES.get(name, []))
        SETTINGS_FILE.write_text(json.dumps(first, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        # "utf-8-sig" also accepts the invisible marker (a "BOM") that some
        # Windows editors put at the start of a file when saving it.
        raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8-sig"))
    except ValueError as error:
        # We never overwrite a broken file: it's yours, and may only need a missing comma.
        raise SettingsError(f"data/actions.json has a mistake on line {error.lineno}: "
                            f"{error.msg}") from error
    except OSError as error:
        raise SettingsError(f"couldn't read data/actions.json ({error.strerror})") from error
    if not isinstance(raw, dict):
        raise SettingsError("data/actions.json should start with { and end with }")
    _add_new_sections(raw)

    problems = []
    apps = _entries(raw, "apps", "open", problems)
    for name, app in apps.items():
        app["process"] = _processes(name, app.get("process", []), problems)
    websites = _entries(raw, "websites", "url", problems)
    folders = _entries(raw, "folders", "path", problems)
    for name, folder in list(folders.items()):
        path = Path(os.path.expandvars(os.path.expanduser(folder["path"].strip())))
        if not path.is_absolute():
            problems.append(f"folder {name}: path must be a full path, like C:\\Users\\you\\Documents")
            del folders[name]
        elif not path.is_dir():
            problems.append(f"folder {name}: {path} doesn't exist on this PC")
            del folders[name]
        else:
            folder["where"] = path.resolve()   # the real place, with any shortcuts followed
    screen = raw.get("screen") if isinstance(raw.get("screen"), dict) else {}
    for name, site in list(websites.items()):
        if not site["url"].lower().startswith(("http://", "https://")):
            problems.append(f"website {name}: url must start with http:// or https://")
            del websites[name]
        elif "search" in site and "{}" not in str(site["search"]):
            problems.append(f"website {name}: search address needs {{}} where the words go")
            del site["search"]
    return {"apps": apps, "websites": websites, "folders": folders,
            "screen": {"hide_hud_from_screenshots": screen.get("hide_hud_from_screenshots") is True},
            "problems": problems}


def _add_new_sections(raw: dict) -> None:
    """
    Files written before "folders" and "screen" existed get them added, with
    the defaults, and are saved again. Everything already in the file stays.
    """
    added = False
    # Program files for close_app, for known apps that don't have one yet.
    for name, app in (raw.get("apps") or {}).items():
        if isinstance(app, dict) and "process" not in app and name in KNOWN_PROCESSES:
            app["process"] = list(KNOWN_PROCESSES[name])
            added = True
    if "folders" not in raw:
        raw["folders"] = _default_folders()
        added = True
    if "screen" not in raw:
        raw["screen"] = dict(DEFAULTS["screen"])
        added = True
    if added:
        if isinstance(raw.get("_how_to"), list):
            raw["_how_to"] += [line for line in HOW_TO_FOLDERS + HOW_TO_CLOSE if line not in raw["_how_to"]]
        SETTINGS_FILE.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")


def _processes(app: str, value, problems: list) -> list[str]:
    """An app's "process" line as a list of program file names, e.g. ["Spotify.exe"]."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        problems.append(f'app {app}: process should be like ["Spotify.exe"]')
        return []
    good = []
    for program in value:
        # Only a program file name ending in .exe: never a folder path or a command.
        if isinstance(program, str) and program.strip().lower().endswith(".exe") \
                and not re.search(r"[\\/:]", program):
            good.append(program.strip())
        else:
            problems.append(f"app {app}: process {program!r} should be a program file name like Spotify.exe")
    return good


def _default_folders() -> dict:
    """Documents, Desktop and Downloads, wherever Windows really keeps them on this PC."""
    folders = {}
    for name, (folder_id, names) in KNOWN_FOLDERS.items():
        path = _known_folder(folder_id) or Path.home() / name
        if path.is_dir():
            folders[name] = {"names": names, "path": str(path)}
    return folders


def _known_folder(folder_id: str) -> Path | None:
    """Ask Windows where one of its special folders is (this only READS it)."""
    try:
        guid = (ctypes.c_byte * 16).from_buffer_copy(uuid.UUID(folder_id).bytes_le)
        found = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(found)) != 0:
            return None
        path = Path(found.value)
        ctypes.windll.ole32.CoTaskMemFree(found)
        return path
    except (OSError, AttributeError, ValueError):
        return None


def _entries(raw: dict, section: str, needed: str, problems: list) -> dict:
    """The good entries of one section ("apps" or "websites"), noting any bad ones."""
    good = {}
    for name, entry in (raw.get(section) or {}).items():
        if not isinstance(entry, dict) or not isinstance(entry.get(needed), str) or not entry[needed].strip():
            problems.append(f"{section[:-1]} {name}: needs \"{needed}\"")
            continue
        names = entry.get("names", [])
        entry["names"] = [n for n in names if isinstance(n, str)] if isinstance(names, list) else []
        good[name] = entry
    return good


def find(section: str, name: str):
    """
    Look up an app, website or folder by any of its names. Returns (friendly
    name, entry), or (None, None) if it isn't in the file. `section` is
    "apps", "websites" or "folders".
    """
    wanted = simplify(name)
    if not wanted:
        return None, None
    for friendly, entry in load()[section].items():
        if wanted in {simplify(n) for n in [friendly, *entry["names"]]}:
            return friendly, entry
    return None, None


def known_names(section: str) -> list[str]:
    """The friendly names in one section, e.g. ["Notepad", "Spotify", ...]."""
    return list(load()[section])


if __name__ == "__main__":
    settings = load()
    print(f"Settings file: {SETTINGS_FILE}")
    for section in ("apps", "websites", "folders"):
        print(f"\n{section.upper()}")
        for friendly, entry in settings[section].items():
            also = f"  (also: {', '.join(entry['names'])})" if entry["names"] else ""
            how = entry.get("open") or entry.get("url") or entry.get("where")
            print(f"  {friendly:<14} {how}{also}")
    print(f"\nSCREEN\n  hide HUD from screenshots: {settings['screen']['hide_hud_from_screenshots']}")
    for problem in settings["problems"]:
        print(f"\nSkipped: {problem}")
