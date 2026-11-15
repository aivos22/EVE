"""
Matching sir's built-in commands ("start fresh", "yes"...), shared by the
brain (gemini_brain.py) and the "ask first" checker (confirm.py).
"""

import re

# Polite or extra words that may come before/after, e.g. "Eve, please start fresh".
FILLER_WORDS = {"eve", "hey", "ok", "okay", "please", "can", "you", "could", "lets", "let's", "now", "just"}


def command_words(text: str) -> str:
    """
    Boil a message down for matching commands: lower case, no punctuation,
    polite words trimmed off both ends. "Eve, start fresh please!" -> "start fresh"
    """
    words = re.sub(r"[^a-z' ]", " ", text.lower()).split()   # lower case, no punctuation
    # Trim polite words off both ends (not the middle).
    while words and words[0] in FILLER_WORDS:
        words.pop(0)
    while words and words[-1] in FILLER_WORDS:
        words.pop()
    return " ".join(words)
