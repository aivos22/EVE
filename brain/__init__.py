"""
The brain package. The voice controller uses `get_brain()` from here.

The Brain itself is only created the first time it's needed, not when
this file is imported. That way, a problem like a missing API key can't
stop the whole HUD from starting.
"""

from brain.gemini_brain import Brain

_brain: Brain | None = None


def get_brain() -> Brain:
    """The one shared Brain, created on first use."""
    global _brain
    if _brain is None:
        _brain = Brain()
    return _brain


def respond(text: str) -> str:
    """Give E.V.E. some text and get her whole reply back."""
    return get_brain().respond(text)


def respond_stream(text: str):
    """Give E.V.E. some text and get her reply back one sentence at a time."""
    return get_brain().respond_stream(text)
