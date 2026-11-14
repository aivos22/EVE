"""
Memory tools: how Gemini saves and forgets facts about sir.

These are thin wrappers around brain/memory.py. Their docstrings are what
Gemini reads to decide WHEN to save something, so they spell that out.
"""


def get_memory():
    # Imported here, when a tool is actually used, not at the top of the file.
    # The brain loads these tools, and these tools use the brain's memory; if
    # both loaded each other at start-up, Python would get stuck in a loop
    # (a "circular import").
    from brain.memory import get_memory as shared_memory
    return shared_memory()


def remember_about_sir(fact: str, replaces: int = 0) -> dict:
    """
    Save a lasting fact about sir to your long-term memory, so you still know it
    in future conversations. Use it when sir tells you something that will stay
    true for a while: his name, job, family and friends' names, likes and
    dislikes, diet, hobbies, routines, goals, projects, important dates, or how
    he likes you to behave. Also use it when he says "remember that...".
    Don't save passing moods, one-off questions, or things already in your memory.
    Save ONE fact per call: if sir tells you several things, call this once for
    each, so any one of them can be updated later without losing the others.

    Args:
        fact: One short sentence about ONE thing, written about sir,
            e.g. "Sir is vegetarian." or "Sir works as a software tester."
        replaces: If this fact updates one you already have (e.g. he has moved),
            the number of the old fact. Otherwise leave as 0.
    """
    return get_memory().remember(fact, replaces)


def forget_about_sir(fact_number: int) -> dict:
    """
    Remove one fact from your long-term memory, by its number. Use it when sir
    asks you to forget something specific, or a fact turns out to be wrong.

    Args:
        fact_number: The number of the fact, as shown in your memory list.
    """
    return get_memory().forget(fact_number)
