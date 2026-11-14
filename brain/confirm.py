"""
"Ask first": for anything that deletes, changes, sends or spends.

The rule: E.V.E. never does something like that straight away. She asks,
and only a plain "yes" from sir, as his very NEXT message, makes it happen.
Anything else cancels it (and is then answered as a normal message).
Questions also run out after ASK_FOR_SECONDS, so an old "are you sure?"
can't be set off by a "yes" much later about something else.

The "yes" is checked here, in E.V.E.'s own code, never by Gemini. So
Gemini can't decide by itself that sir agreed, however it reads things.

How a risky action uses it, e.g. a future delete_file tool:

    from brain.confirm import ask_first

    def delete_file(name: str) -> dict:
        ...check the name is allowed...
        def do_it() -> str:
            path.unlink()
            return f"Done, sir. {name} is deleted."
        return ask_first(f"Just to be sure, sir: delete {name}? Say yes to confirm.",
                         do_it, description=f"delete {name}")

The brain then says the question, and handles sir's answer (see
respond_stream in gemini_brain.py). Every question, yes, cancel and
time-out is written in the diary.
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Callable

from brain.commands import command_words

ASK_FOR_SECONDS = 120   # how long a question waits for an answer

# The answers that count as yes (after command_words(): lower case, no
# punctuation, polite words like "please" trimmed off).
YES_WORDS = {"yes", "yes forget everything", "yes do it", "yes i'm sure", "yes im sure",
             "yes go ahead", "go ahead", "confirm", "confirmed", "do it", "i'm sure",
             "im sure", "yep", "yeah", "yes please"}

diary = logging.getLogger("eve")


@dataclass
class Question:
    question: str              # what she asked, e.g. "...Say yes to confirm."
    do_it: Callable[[], str]   # does the action; returns what she says afterwards
    description: str           # for the diary, e.g. "wipe long-term memory"
    asked_at: float


_waiting: Question | None = None
_lock = threading.Lock()


def is_yes(text: str) -> bool:
    return command_words(text) in YES_WORDS


def ask_first(question: str, do_it: Callable[[], str], description: str) -> dict:
    """
    Don't do it yet: remember it, and have her ask `question`.
    Returns a tool result whose "say" line is the question.
    """
    global _waiting
    with _lock:
        _waiting = Question(question, do_it, description, time.monotonic())
    diary.info(f"[CONFIRM] Asked sir: {description}")
    return {"waiting_for_sir": "Asked sir to confirm. Nothing done yet.", "say": question}


def answer(text: str):
    """
    Called by the brain with EVERY message from sir, before anything else.
    If a question was waiting:
      - "yes"        -> the action runs; returns what she should say
      - anything else -> it's cancelled; returns None, so the message is
                         answered normally
    With no question waiting, returns None.
    """
    global _waiting
    with _lock:
        waiting, _waiting = _waiting, None   # a question is only ever answered once
    if waiting is None:
        return None
    if time.monotonic() - waiting.asked_at > ASK_FOR_SECONDS:
        diary.info(f"[CONFIRM] Ran out of time, not done: {waiting.description}")
        return None
    if not is_yes(text):
        diary.info(f"[CONFIRM] Sir didn't say yes, cancelled: {waiting.description}")
        return None
    diary.info(f"[CONFIRM] Sir said yes: {waiting.description}")
    try:
        return waiting.do_it()
    except Exception as error:
        diary.exception(f"[CONFIRM] Failed: {waiting.description}")
        return f"I'm afraid that didn't work, sir: {type(error).__name__}."


def waiting_for() -> str:
    """What's waiting for a yes, for the log, or "" if nothing is."""
    with _lock:
        return _waiting.description if _waiting else ""
