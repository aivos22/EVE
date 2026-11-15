"""
Files, read-only: find, list and open files, but ONLY inside the folders
listed under "folders" in data/actions.json (Documents, Desktop and
Downloads to start with; add your own, like your EPQ folder).

    find_files(name, folder)        search file names, newest first
    list_folder(folder, subfolder)  what's in a folder, newest first
    open_file(name, folder)         open a file with its usual app

Safety:
  - Every path is checked to really be inside an allowed folder AFTER
    following any shortcuts, so tricks like "..\\..\\Windows" or a link
    that points somewhere else are refused.
  - open_file won't open programs or scripts (.exe, .bat, .ps1...).
    "Opening" those means RUNNING them, which would get round the app
    allowlist. Apps are opened with open_app instead.
  - Nothing here moves, renames, changes or deletes anything. When those
    are added later, they MUST use the ask-first pattern in brain/confirm.py.

What goes to Gemini: file and folder names and dates, never what's
inside a file.

Searching a big folder takes a moment, but tools run on the brain's
background thread, so the HUD never freezes. A search also gives up after
SEARCH_SECONDS, so a huge folder can't keep her thinking forever.

Test it alone:
    .venv\\Scripts\\python -m actions find essay
    .venv\\Scripts\\python -m actions list documents
    .venv\\Scripts\\python -m actions open_file notes.docx
"""

import os
import re
import time
from datetime import datetime
from pathlib import Path

from actions import settings

MAX_RESULTS = 10        # files found per search
MAX_LISTED = 25         # items per folder listing
SEARCH_SECONDS = 4      # a search stops after this long, with what it found so far
# Folders never searched: hidden ones (starting with "."), and big ones full of code bits.
SKIP_FOLDERS = {"node_modules", "__pycache__", "$recycle.bin", "venv", ".venv", "site-packages"}
# Opening these RUNS something, so open_file refuses them.
RUNNABLE = {".exe", ".bat", ".cmd", ".com", ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse", ".wsf",
            ".wsh", ".msi", ".msp", ".scr", ".pif", ".lnk", ".url", ".hta", ".cpl", ".jar", ".py",
            ".pyw", ".reg", ".appref-ms", ".application", ".msc", ".sh", ".ahk"}

NOT_ALLOWED_SAY = ("I'm not allowed into {name}, sir. You can add it to the folders section "
                   "of the actions file in my data folder.")
SETTINGS_BROKEN = "My actions file has a mistake in it, sir. The log has the details."


class Refused(Exception):
    """A plain reason, plus what she says, for a folder that can't be used."""
    def __init__(self, error: str, say: str, **extra):
        super().__init__(error)
        self.result = {"error": error, "say": say, **extra}


# --- Which folders ----------------------------------------------------------

def _allowed() -> dict[str, Path]:
    """{friendly name: real place} for every allowed folder that exists."""
    try:
        return {name: entry["where"] for name, entry in settings.load()["folders"].items()}
    except settings.SettingsError as error:
        raise Refused(str(error), SETTINGS_BROKEN)


def _inside(path: Path, roots) -> bool:
    """True if `path`, with shortcuts followed, is inside one of the allowed folders."""
    try:
        real = path.resolve()
    except OSError:
        return False
    return any(real == root or real.is_relative_to(root) for root in roots)


def _folders_for(folder: str) -> dict[str, Path]:
    """
    The allowed folder(s) to use. `folder` can be empty (all of them), a
    name from the settings ("documents", "my epq"), or a full path that's
    inside an allowed folder ("C:\\Users\\chris\\Documents\\School").
    """
    allowed = _allowed()
    if not allowed:
        raise Refused("no folders are allowed yet",
                      "I haven't been given any folders yet, sir. You can add them to the folders "
                      "section of the actions file in my data folder.")
    folder = (folder or "").strip()
    if not folder:
        return allowed
    friendly, _ = settings.find("folders", folder)
    if friendly in allowed:
        return {friendly: allowed[friendly]}
    as_path = Path(os.path.expandvars(os.path.expanduser(folder)))
    if as_path.is_absolute() and as_path.is_dir() and _inside(as_path, allowed.values()):
        return {as_path.name: as_path.resolve()}
    raise Refused(f"{folder} isn't an allowed folder", NOT_ALLOWED_SAY.format(name=folder),
                  allowed_folders=list(allowed),
                  tell_sir="Add it under \"folders\" in data/actions.json to let me in.")


def _shown(path: Path, folders: dict[str, Path]) -> str:
    """'EPQ\\Drafts\\essay.docx': the allowed folder's name, then the rest, never the full path."""
    real = path.resolve()
    for name, root in folders.items():
        if real == root or real.is_relative_to(root):
            rest = real.relative_to(root)
            return name if str(rest) == "." else f"{name}\\{rest}"
    return path.name


def _when(seconds: float) -> str:
    """When it was last changed, written for speaking: '12 November 2026'."""
    when = datetime.fromtimestamp(seconds)
    return f"{when.day} {when:%B %Y}"


# --- Searching ----------------------------------------------------------------

def _search(name: str, folders: dict[str, Path]) -> tuple[list[Path], bool]:
    """
    Files whose names contain every word of `name`, best first.
    Returns (matches, finished): finished is False if it ran out of time.
    """
    words = settings.simplify_words(name)
    if not words:
        return [], True
    wanted = "".join(words)
    stop_at = time.monotonic() + SEARCH_SECONDS
    found: list[tuple[tuple, Path]] = []
    roots = list(folders.values())
    for root in roots:
        # os.walk visits every folder inside `root`. Changing `dirs` in
        # place tells it which subfolders to skip.
        for here, dirs, files in os.walk(root, onerror=lambda _: None):
            if time.monotonic() > stop_at:
                return _best(found), False
            dirs[:] = [d for d in dirs if not d.startswith((".", "~")) and d.lower() not in SKIP_FOLDERS]
            for file in files:
                plain = settings.simplify(file)
                # Each word must START a word in the file's name, so "new me"
                # finds "NEW ME.txt" but not "Newtime.fst". (Or the words
                # joined up appear in it, so "newme" still finds "NEW ME".)
                file_words = re.split(r"[^a-z0-9]+", file.lower())
                if not (wanted in plain
                        or all(any(fw.startswith(word) for fw in file_words) for word in words)):
                    continue
                path = Path(here) / file
                if not _inside(path, roots):
                    continue   # a shortcut pointing outside the allowed folders
                stem = settings.simplify(Path(file).stem)
                try:
                    changed = path.stat().st_mtime
                except OSError:
                    continue
                # Best first: exact name, then names starting with it, then newest.
                found.append(((stem != wanted and plain != wanted, not stem.startswith(wanted), -changed), path))
    return _best(found), True


def _best(found):
    return [path for _, path in sorted(found, key=lambda pair: pair[0])]


def _describe(path: Path, folders: dict[str, Path]) -> dict:
    try:
        changed = _when(path.stat().st_mtime)
    except OSError:
        changed = "unknown"
    return {"name": path.name, "in": str(Path(_shown(path, folders)).parent), "changed": changed}


# --- The tools Gemini can use ---------------------------------------------------

def find_files(name: str, folder: str = "") -> dict:
    """
    Search sir's allowed folders for files by name. Use it when sir asks
    where a file is, whether he has a file, or to find one. Only the
    folders in sir's list can be searched; if the result says a folder
    isn't allowed, tell him briefly, including which file to add it to.
    Never say full paths out loud: say the file name and folder.

    Args:
        name: Words from the file's name, e.g. "essay" or "physics notes".
        folder: Which allowed folder to search, e.g. "documents" or "EPQ".
            Leave empty to search all of them.
    """
    try:
        folders = _folders_for(folder)
    except Refused as refused:
        return refused.result
    matches, finished = _search(name, folders)
    where = ", ".join(folders)
    if not matches:
        more = "" if finished else " I ran out of time before searching everywhere, though."
        return {"found": [], "searched": list(folders),
                "say": f"I couldn't find any files called {name} in {where}, sir.{more}"}
    result = {"found": [_describe(p, folders) for p in matches[:MAX_RESULTS]],
              "total_found": len(matches), "searched": list(folders)}
    if not finished:
        result["note"] = f"stopped after {SEARCH_SECONDS} seconds, so there may be more"
    return result


def list_folder(folder: str = "", subfolder: str = "") -> dict:
    """
    List what's in one of sir's allowed folders, newest first. Use it when
    sir asks what's in a folder, or what he's been working on recently.

    Args:
        folder: Which allowed folder, e.g. "documents", "downloads" or "EPQ".
            Leave empty to list the allowed folders themselves.
        subfolder: A folder inside it, if sir named one, e.g. "drafts".
    """
    try:
        if not (folder or "").strip():
            return {"allowed_folders": list(_allowed())}
        folders = _folders_for(folder)
    except Refused as refused:
        return refused.result
    name, root = next(iter(folders.items()))
    place = root / subfolder if subfolder else root
    if not _inside(place, [root]) or not place.is_dir():
        return {"error": f"there's no folder called {subfolder} in {name}",
                "say": f"There's no folder called {subfolder} in {name}, sir."}
    items = []
    try:
        for item in place.iterdir():
            if item.name.startswith((".", "~$")) or item.name.lower() in ("desktop.ini", "thumbs.db"):
                continue
            try:
                items.append((item.stat().st_mtime, item))
            except OSError:
                continue
    except OSError as error:
        return {"error": f"couldn't read {name}: {error.strerror or error}",
                "say": f"Windows wouldn't let me look in {name}, sir."}
    items.sort(key=lambda pair: -pair[0])
    shown = [{"name": item.name, "kind": "folder" if item.is_dir() else "file", "changed": _when(changed)}
             for changed, item in items[:MAX_LISTED]]
    if not shown:
        return {"folder": _shown(place, folders), "items": [], "say": f"{name} is empty, sir."}
    return {"folder": _shown(place, folders), "items": shown, "total": len(items)}


def open_file(name: str, folder: str = "") -> dict:
    """
    Open one of sir's files with its usual app (Word, a PDF reader...).
    Only files in sir's allowed folders can be opened. If several files
    match, the result lists them: ask sir which one he means, briefly.

    Args:
        name: The file's name, or words from it, e.g. "essay draft" or "notes.docx".
        folder: Which allowed folder it's in, if sir said. Otherwise leave empty.
    """
    try:
        folders = _folders_for(folder)
    except Refused as refused:
        return refused.result
    matches, _ = _search(name, folders)
    if not matches:
        return {"error": f"no file called {name}",
                "say": f"I couldn't find a file called {name}, sir."}
    wanted = "".join(settings.simplify_words(name))
    exact = [p for p in matches if wanted in (settings.simplify(p.stem), settings.simplify(p.name))]
    if len(matches) == 1:
        chosen = matches[0]
    elif len(exact) == 1:
        chosen = exact[0]
    else:   # no "say" line: Gemini asks sir which one, from this list
        return {"several_match": [_describe(p, folders) for p in matches[:MAX_RESULTS]],
                "ask_sir": "Which one? Nothing has been opened yet."}
    if chosen.suffix.lower() in RUNNABLE:
        return {"error": f"{chosen.name} is a program or script, so opening it would run it",
                "say": f"{chosen.name} is a program, sir, so I won't run it. I only open documents."}
    if not _inside(chosen, folders.values()):   # checked once more, just before opening
        return {"error": "that file is outside the allowed folders", "say": NOT_ALLOWED_SAY.format(name="that folder")}
    try:
        os.startfile(chosen)   # the same as double-clicking it
    except OSError as error:
        return {"error": f"Windows couldn't open {chosen.name}: {error.strerror or error}",
                "say": f"Windows wouldn't open {chosen.name} for me, sir."}
    return {"opened": chosen.name, "in": str(Path(_shown(chosen, folders)).parent),
            "say": f"Opening {chosen.stem}, sir."}
