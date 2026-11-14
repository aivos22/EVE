"""
E.V.E.'s actions: things she can DO, rather than just say.

Two kinds of tool:
  - look-ups (weather, Wikipedia, web search, memory): Gemini reads the
    result and puts it into words
  - actions (open apps and websites, timers): these do something on the PC,
    and only from an allowlist (data/actions.json), never a free-form command

Each one is a plain Python function with a docstring explaining what it's
for. That docstring matters: it's what Gemini reads to decide when to use
the tool and what to pass it.

Quick replies: an action can return a ready-made "say" line, e.g.
{"opened": "Spotify", "say": "Opening Spotify, sir."}. If every tool in a
round has one, the brain says those lines straight away instead of asking
Gemini to word the answer: one Gemini request instead of two.

Safety rules for actions, now and later:
  - allowlists, never free-form commands
  - anything that deletes, changes, sends or spends must ask sir first and
    wait for "yes" (see brain/confirm.py)
  - every action is written in the diary (run_tool does this)

To add a new tool later:
  1. write the function (in its own file in this folder)
  2. add it to TOOLS below, and give it a log label in LABELS
"""

import json
import logging

from actions import settings
from actions.apps import open_app
from actions.memory_tools import forget_about_sir, remember_about_sir
from actions.timers import cancel_timer, list_timers, say_duration, set_timer, tidy_label
from actions.weather import get_weather
from actions.web_search import search_web
from actions.websites import open_website
from actions.wikipedia import look_up_wikipedia

TOOLS = [get_weather, look_up_wikipedia, search_web, remember_about_sir, forget_about_sir,
         open_app, open_website, set_timer, cancel_timer, list_timers]
_BY_NAME = {tool.__name__: tool for tool in TOOLS}

diary = logging.getLogger("eve")

# What the log says while each tool runs, e.g. "[ACTION] Checking weather: Leeds".
LABELS = {
    "get_weather": "Checking weather",
    "look_up_wikipedia": "Looking up",
    "search_web": "Searching the web",
    "remember_about_sir": "Remembering",
    "forget_about_sir": "Forgetting fact",
    "cancel_timer": "Cancelling timer",
    "list_timers": "Checking timers",
}


def _friendly(section: str, name: str) -> str:
    """The name as written in data/actions.json ("spotify" -> "Spotify"), if it's there."""
    try:
        found, _ = settings.find(section, name)
    except settings.SettingsError:
        found = None
    return found or name


def _timer_line(args: dict) -> str:
    seconds = sum(float(args.get(unit) or 0) * size
                  for unit, size in (("hours", 3600), ("minutes", 60), ("seconds", 1)))
    details = [tidy_label(str(args.get("label", ""))), say_duration(seconds)]
    return "Setting timer: " + ", ".join(d for d in details if d)


# Some tools get a line written specially, e.g. "Opening Spotify" or
# "Searching YouTube: lo-fi beats", instead of "label: first detail".
SPECIAL_LINES = {
    "open_app": lambda args: f"Opening {_friendly('apps', args.get('name', ''))}",
    "open_website": lambda args: (
        f"Searching {_friendly('websites', args.get('site', ''))}: {args['search']}" if args.get("search")
        else f"Opening {_friendly('websites', args.get('site', ''))}"),
    "set_timer": _timer_line,
}


def describe(name: str, args: dict) -> str:
    """A short line for the log saying what's happening."""
    if name in SPECIAL_LINES:
        try:
            return SPECIAL_LINES[name](args)
        except Exception:
            pass   # odd arguments: fall back to the plain line below
    # The first filled-in detail, preferring text (e.g. the fact, not its number).
    values = sorted((value for value in args.values() if value), key=lambda v: not isinstance(v, str))
    detail = str(values[0]) if values else ""
    label = LABELS.get(name, f"Running {name}")
    return f"{label}: {detail}" if detail else label


def run_tool(name: str, args: dict) -> dict:
    """
    Run the tool called `name` with `args`, and ALWAYS return a dict, even
    if it fails. A failure comes back as {"error": "..."}, which Gemini reads
    and explains politely, instead of the whole reply crashing.

    Every call is written in the diary with what came back, e.g.
        [TOOL] open_app {"name": "spotify"} -> {"opened": "Spotify", ...}
    """
    tool = _BY_NAME.get(name)
    if tool is None:
        result = {"error": f"There's no tool called {name}"}
    else:
        try:
            result = tool(**args)
        except Exception as error:   # no internet, website down, odd answer...
            # The type and message say whether it was the internet, the website, or our code.
            diary.warning(f"Tool {name}({args}) failed: {error!r}")
            result = {"error": f"{name} failed: {type(error).__name__}: {error}"[:200]}
    shown = json.dumps(result, ensure_ascii=False, default=str)
    diary.info(f"[TOOL] {name} {json.dumps(args, ensure_ascii=False, default=str)} -> "
               + (shown if len(shown) <= 300 else shown[:300] + "..."))
    return result
