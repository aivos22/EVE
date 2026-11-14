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

from actions.weather import get_weather
from actions.web_search import search_web
from actions.wikipedia import look_up_wikipedia

TOOLS = [get_weather, look_up_wikipedia, search_web]
_BY_NAME = {tool.__name__: tool for tool in TOOLS}

# What the log says while each tool runs, e.g. "[ACTION] Checking weather: Leeds".
LABELS = {
    "get_weather": "Checking weather",
    "look_up_wikipedia": "Looking up",
    "search_web": "Searching the web",
}


def describe(name: str, args: dict) -> str:
    """A short line for the log saying what's happening."""
    detail = next((str(value) for value in args.values() if isinstance(value, str) and value), "")
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
