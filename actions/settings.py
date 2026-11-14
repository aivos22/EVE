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

See what's set up:   .venv\\Scripts\\python -m actions.settings
"""

import json
import re

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


def load() -> dict:
    """
    Read data/actions.json (creating it with the defaults if it's missing).
    Returns {"apps": {...}, "websites": {...}, "problems": [...]}, where
    problems lists any entries that were skipped because they were filled
    in wrongly, so one typo doesn't switch everything off.
    """
    if not SETTINGS_FILE.exists():
        SETTINGS_FILE.write_text(json.dumps(DEFAULTS, indent=2, ensure_ascii=False), encoding="utf-8")
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

    problems = []
    apps = _entries(raw, "apps", "open", problems)
    websites = _entries(raw, "websites", "url", problems)
    for name, site in list(websites.items()):
        if not site["url"].lower().startswith(("http://", "https://")):
            problems.append(f"website {name}: url must start with http:// or https://")
            del websites[name]
        elif "search" in site and "{}" not in str(site["search"]):
            problems.append(f"website {name}: search address needs {{}} where the words go")
            del site["search"]
    return {"apps": apps, "websites": websites, "problems": problems}


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
    Look up an app or website by any of its names. Returns (friendly name, entry),
    or (None, None) if it isn't in the file. `section` is "apps" or "websites".
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
    for section in ("apps", "websites"):
        print(f"\n{section.upper()}")
        for friendly, entry in settings[section].items():
            also = f"  (also: {', '.join(entry['names'])})" if entry["names"] else ""
            how = entry.get("open") or entry.get("url")
            print(f"  {friendly:<14} {how}{also}")
    for problem in settings["problems"]:
        print(f"\nSkipped: {problem}")
