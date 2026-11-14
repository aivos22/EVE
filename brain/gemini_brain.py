"""
E.V.E.'s brain: sends what you said to Google's Gemini and gets her reply.

Each request sends three things:
  1. her personality (brain/personality.txt), as the "system instruction"
  2. the recent conversation, so she remembers what you've been talking about
  3. your new message

The conversation is capped at MAX_EXCHANGES back-and-forths, so it never
grows forever (and each request stays quick and cheap).

This file knows nothing about the HUD or the voice. It just turns text
into a reply, so it can be tested on its own:  .venv\\Scripts\\python -m brain
"""

import os
import re
from pathlib import Path

from google import genai
from google.genai import types

PERSONALITY_FILE = Path(__file__).parent / "personality.txt"

# Which Gemini model to use. Tested Nov 2026: 3.5 Flash-Lite answers in under
# a second and still sounds like her; full 3.5 Flash took 2-20 seconds. To try
# a different one without touching code, add e.g.
#     EVE_GEMINI_MODEL=gemini-3.5-flash
# to .env.
DEFAULT_MODEL = "gemini-3.5-flash-lite"
# How hard the model "thinks" before answering. "minimal" = fastest replies,
# which matters more than deep reasoning for a spoken assistant.
THINKING_LEVEL = "minimal"

MAX_EXCHANGES = 10      # how many of your messages (and her replies) she remembers
TIMEOUT_SECONDS = 20    # give up on a request after this long, so she never hangs
# A hard cap on the reply. It's generous because the model's hidden "thinking"
# counts towards it too; personality.txt is what actually keeps answers short.
MAX_REPLY_TOKENS = 2000


class Brain:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("No GEMINI_API_KEY in .env")
        self.model = os.getenv("EVE_GEMINI_MODEL", DEFAULT_MODEL)
        # The client is our connection to Gemini. Timeout is in milliseconds.
        self.client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=TIMEOUT_SECONDS * 1000),
        )
        self.personality = PERSONALITY_FILE.read_text(encoding="utf-8")
        # The conversation so far: a list of messages, alternating "user" and "model".
        self.history: list[types.Content] = []

    def respond(self, text: str) -> str:
        """Send `text` to Gemini and return E.V.E.'s reply as plain spoken text."""
        message = types.Content(role="user", parts=[types.Part(text=text)])
        response = self.client.models.generate_content(
            model=self.model,
            contents=self.history + [message],
            config=types.GenerateContentConfig(
                system_instruction=self.personality,
                max_output_tokens=MAX_REPLY_TOKENS,
                thinking_config=types.ThinkingConfig(thinking_level=THINKING_LEVEL),
            ),
        )
        reply = clean_for_speech(response.text or "")
        if not reply:
            reply = "I'm afraid I drew a blank there, sir."

        # Only remember the exchange once it has worked.
        self.history.append(message)
        self.history.append(types.Content(role="model", parts=[types.Part(text=reply)]))
        # Each exchange is 2 messages; keep only the most recent ones.
        self.history = self.history[-MAX_EXCHANGES * 2:]
        return reply

    def forget(self) -> None:
        """Wipe the conversation memory (a fresh start)."""
        self.history.clear()


def clean_for_speech(text: str) -> str:
    """
    A safety net in case Gemini uses formatting anyway: strip markdown
    symbols that would sound odd read aloud, and join lines into one paragraph.
    """
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)          # code blocks
    text = re.sub(r"^\s*(#+|[-*•]|\d+[.)])\s+", "", text, flags=re.MULTILINE)  # headings, bullets, "1."
    text = re.sub(r"[*_`#]", "", text)                               # leftover bold/italic/code marks
    text = re.sub(r"\s+", " ", text)                                 # newlines and double spaces -> one space
    return text.strip()
