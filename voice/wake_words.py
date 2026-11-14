"""
The words that wake E.V.E. up, put her back to sleep, or shut her down.

    "Eve, what's the weather?"   -> wake word + question: she answers it
    "What's the time, Eve?"      -> her name at the end works too
    "Hey Eve" / "Eve"            -> just her name: she says "Yes, sir?" and listens
    "Thanks Eve" / "That's all"  -> sleep: she stops listening for a follow-up
    "Eve, shut down"             -> she plays the shutdown animation and closes

Sleep and shut-down only count if they are the WHOLE message, so
"How do I shut down my laptop?" is still a normal question.

This file is plain text matching: no microphone, no Gemini. Test it with
    .venv\\Scripts\\python -m voice.wake_words
"""

import re

# Her name, and spellings Whisper sometimes writes for it.
NAMES = ("eve", "eva", "evie")
# Words that may come before her name: "Hey Eve", "OK Eve".
GREETINGS = ("hey", "hi", "hello", "ok", "okay", "oh", "right")

# The regular expressions ("patterns") that spot her name at the start or end.
_NAME = "|".join(NAMES)
_GREETING = "|".join(GREETINGS)
# Start: optional greeting, her name, then any punctuation, then the rest.
_AT_START = re.compile(rf"^\s*(?:(?:{_GREETING})[\s,.!]+)?(?:{_NAME})\b[\s,.!?:;-]*(.*)$",
                       re.IGNORECASE | re.DOTALL)
# End: the request, a comma or space, her name, then punctuation.
_AT_END = re.compile(rf"^(.*?)[\s,]+(?:{_NAME})[\s.!?]*$", re.IGNORECASE | re.DOTALL)

# Write these in lower case, without punctuation.
SLEEP_PHRASES = {
    "thanks", "thank you", "cheers", "that's all", "thats all", "that is all",
    "that will be all", "that'll be all", "thatll be all", "that's it", "thats it",
    "goodbye", "bye", "bye bye", "good night", "goodnight", "night",
    "never mind", "nevermind", "nothing", "cancel", "go to sleep", "sleep",
    "stop listening", "ok thanks", "okay thanks", "ok thank you", "okay thank you",
}
SHUTDOWN_PHRASES = {
    "shut down", "shutdown", "shut yourself down", "power down", "power off",
    "switch off", "turn off", "turn yourself off", "switch yourself off",
    "shut down now", "close", "quit", "exit", "log off", "go offline",
}
# What she says for each.
WAKE_REPLY = "Yes, sir?"
SLEEP_REPLY = "Very good, sir."
SHUTDOWN_REPLY = "Shutting down, sir."

# Polite words trimmed off both ends before matching: "Eve, please shut down" -> "shut down".
_FILLER = {"eve", "eva", "evie", "hey", "ok", "okay", "please", "now", "just", "you", "can", "could"}


def split_wake(text: str) -> str | None:
    """
    If `text` is addressed to her (her name at the start or end), return
    the rest of it: "Eve, what's the time?" -> "what's the time?".
    Just her name returns "". Not addressed to her returns None.
    """
    match = _AT_START.match(text)
    if match:
        return match.group(1).strip()
    match = _AT_END.match(text)
    if match:
        return match.group(1).strip(" ,")
    return None


def _command(text: str) -> str:
    """Boil text down for matching: lower case, no punctuation, polite words trimmed."""
    words = re.sub(r"[^a-z' ]", " ", text.lower()).split()
    while words and words[0] in _FILLER:
        words.pop(0)
    while words and words[-1] in _FILLER:
        words.pop()
    return " ".join(words)


def wants_sleep(text: str) -> bool:
    return _command(text) in SLEEP_PHRASES


def wants_shutdown(text: str) -> bool:
    return _command(text) in SHUTDOWN_PHRASES


if __name__ == "__main__":
    # Quick check of the rules, no microphone needed.
    examples = [
        "Eve, what's the weather?", "What's the time, Eve?", "Hey Eve.", "Eve",
        "Steve is coming round", "Thanks Eve.", "That's all.", "Eve, shut down.",
        "Eve, please power off", "How do I shut down my laptop?", "evening all",
    ]
    for line in examples:
        rest = split_wake(line)
        verdict = ("ignored (not for her)" if rest is None
                   else "SHUT DOWN" if wants_shutdown(rest)
                   else "SLEEP" if wants_sleep(rest)
                   else "WAKE: \"Yes, sir?\"" if rest == ""
                   else f"ask the brain: \"{rest}\"")
        print(f"{line!r:40} -> {verdict}")
