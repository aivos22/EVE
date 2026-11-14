"""
The brain package. The voice controller looks for `respond` here.

The Brain itself is only created the first time respond() is called, not
when this file is imported. That way, a problem like a missing API key
can't stop the whole HUD from starting.
"""

from brain.gemini_brain import Brain

_brain: Brain | None = None


def respond(text: str) -> str:
    """Give E.V.E. some text and get her reply back."""
    global _brain
    if _brain is None:
        _brain = Brain()
    return _brain.respond(text)
