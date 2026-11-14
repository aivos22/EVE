"""
E.V.E.'s actions: things she can DO, rather than just say.

For now these are "look it up" tools. Each one is a plain Python function
with a docstring explaining what it's for. That docstring matters: it's
what Gemini reads to decide when to use the tool and what to pass it.

To add a new tool later:
  1. write the function (in its own file in this folder)
  2. add it to TOOLS below, and give it a log label in LABELS
"""

import logging

from actions.apps import open_app
from actions.memory_tools import forget_about_sir, remember_about_sir
from actions.timers import cancel_timer, list_timers, set_timer
from actions.weather import get_weather
from actions.web_search import search_web
from actions.websites import open_website
from actions.wikipedia import look_up_wikipedia

TOOLS = [get_weather, look_up_wikipedia, search_web, remember_about_sir, forget_about_sir]
# Built, and testable with "python -m actions", but not offered to Gemini yet.
# (Step 5 of the actions work moves these into TOOLS.)
NOT_WIRED_YET = [open_app, open_website, set_timer, cancel_timer, list_timers]
_BY_NAME = {tool.__name__: tool for tool in TOOLS + NOT_WIRED_YET}

# What the log says while each tool runs, e.g. "[ACTION] Checking weather: Leeds".
LABELS = {
    "get_weather": "Checking weather",
    "look_up_wikipedia": "Looking up",
    "search_web": "Searching the web",
    "remember_about_sir": "Remembering",
    "forget_about_sir": "Forgetting fact",
    "open_app": "Opening",
    "open_website": "Opening",
    "set_timer": "Setting timer",
    "cancel_timer": "Cancelling timer",
    "list_timers": "Checking timers",
}


def describe(name: str, args: dict) -> str:
    """A short line for the log saying what's happening."""
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
    """
    tool = _BY_NAME.get(name)
    if tool is None:
        return {"error": f"There's no tool called {name}"}
    try:
        return tool(**args)
    except Exception as error:   # no internet, website down, odd answer...
        # The diary (data/logs/) gets one line with the error type and message,
        # which says whether it was the internet, the website, or our code.
        logging.getLogger("eve").warning(f"Tool {name}({args}) failed: {error!r}")
        return {"error": f"{name} failed: {type(error).__name__}: {error}"[:200]}
