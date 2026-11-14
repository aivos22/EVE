"""
E.V.E.'s brain: sends what you said to Google's Gemini and gets her reply.

Each request sends three things:
  1. her personality (brain/personality.txt), as the "system instruction"
  2. the recent conversation, so she remembers what you've been talking about
  3. your new message

She has two modes (see MODES below):
  fast  - the quick model, and the reply is STREAMED: it arrives a few words
          at a time, and we hand out each sentence as soon as it's complete,
          so she can start speaking before the rest is written.
  think - a stronger model that thinks harder first. The full answer is
          written before she says anything, so it takes longer.

Either way, respond_stream() hands out the reply one sentence at a time.
The voice uses that to start speaking sentence one while sentence two is
still being made into audio.

The conversation is capped at MAX_EXCHANGES back-and-forths, so it never
grows forever (and each request stays quick and cheap).

She can also use tools from the actions/ folder (weather, Wikipedia, web
search). Gemini decides when a question needs one; see _text_pieces().

This file knows nothing about the HUD or the voice. It just turns text
into a reply, so it can be tested on its own:  .venv\\Scripts\\python -m brain
"""

import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from google import genai
from google.genai import errors, types

# google-genai talks to the internet through a web library: "httpx2" in the
# version we have, plain "httpx" in older ones. We only need their error
# types, so we collect them from whichever is installed.
import httpx
try:
    import httpx2
except ImportError:
    httpx2 = None
_WEB_LIBS = [lib for lib in (httpx, httpx2) if lib]
TIMEOUT_ERRORS = tuple(lib.TimeoutException for lib in _WEB_LIBS)   # took too long
CONNECTION_ERRORS = tuple(lib.TransportError for lib in _WEB_LIBS)  # couldn't connect at all
WEB_ERRORS = tuple(lib.HTTPError for lib in _WEB_LIBS)              # any of the above, and more

PERSONALITY_FILE = Path(__file__).parent / "personality.txt"

# Her tools (weather, Wikipedia, web search) live in the actions/ folder.
# If that folder is missing or broken, she just works without them.
try:
    from actions import TOOLS, run_tool
    from actions import describe as describe_tool
except ImportError:
    TOOLS = []
MAX_TOOL_ROUNDS = 3   # at most this many look-ups before she must answer


@dataclass
class Mode:
    label: str          # shown in the log, e.g. "Fast"
    model: str          # which Gemini model
    thinking: str       # how hard it thinks first: "minimal", "low", "medium" or "high"
    stream: bool        # True = hand out sentences while the reply is still arriving
    timeout: int        # seconds to wait before giving up


# The two modes. Each model can be changed in .env without touching code,
# e.g.  EVE_FAST_MODEL=gemini-3.5-flash-lite   or   EVE_THINK_MODEL=gemini-3.8-flash
# Tested Nov 2026: 3.5 Flash-Lite answers in under a second and still sounds like her.
MODES = {
    "fast": Mode("Fast", os.getenv("EVE_FAST_MODEL", "gemini-3.5-flash-lite"), "minimal", True, 20),
    "think": Mode("Think", os.getenv("EVE_THINK_MODEL", "gemini-3.5-flash"), "high", False, 30),
}
DEFAULT_MODE = "fast"

MAX_EXCHANGES = 10      # how many of your messages (and her replies) she remembers
# A hard cap on the reply. It's generous because the model's hidden "thinking"
# counts towards it too; personality.txt is what actually keeps answers short.
MAX_REPLY_TOKENS = 8000
# Error numbers that mean "Google's side is busy or broken right now", not
# "you did something wrong". In think mode we fall back to the fast model.
BUSY_CODES = (429, 500, 503, 504)


class BrainError(Exception):
    """
    The brain couldn't get a reply. The message is a short, plain reason for
    the log, e.g. "no internet connection" or "API key not valid".
    """


def explain(error: Exception) -> str:
    """Turn a technical error into a short, plain reason for the log."""
    if isinstance(error, TIMEOUT_ERRORS):
        return "Gemini took too long to answer"
    if isinstance(error, CONNECTION_ERRORS):
        return "no internet connection"
    if isinstance(error, errors.APIError):
        message = (error.message or "").lower()
        if "api key" in message or error.code in (401, 403):
            return "API key not valid (check GEMINI_API_KEY in .env)"
        if error.code == 429:
            return "too many requests, or out of free quota"
        if error.code == 404:
            return "model not found (check the model names in brain/gemini_brain.py)"
        if error.code >= 500:
            return f"Gemini is having problems ({error.code})"
        return f"Gemini error {error.code}: {error.message}"[:90]
    return f"{type(error).__name__}: {error}"[:90]


class Brain:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise BrainError("no GEMINI_API_KEY in .env")
        # The client is our connection to Gemini.
        self.client = genai.Client(api_key=api_key)
        self.personality = PERSONALITY_FILE.read_text(encoding="utf-8")
        # The conversation so far: a list of messages, alternating "user" and "model".
        self.history: list[types.Content] = []
        wanted = os.getenv("EVE_BRAIN_MODE", DEFAULT_MODE).strip().lower()
        self.mode = wanted if wanted in MODES else DEFAULT_MODE
        # Something to call with short notes for the log (e.g. "think model busy").
        # The voice controller swaps this for its own log; on its own, we just print.
        self.on_note = print
        # Called with e.g. "Checking weather: Leeds" when a tool starts, and
        # with None when the tools are done. The voice uses it for the log and
        # the eye's LOOKING state. On its own, we print it.
        self.on_tool = lambda text: text and print(f"       ({text})")

    # --- Modes ----------------------------------------------------------

    def toggle_mode(self) -> str:
        """Switch fast <-> think. Returns the new mode's name."""
        self.mode = "think" if self.mode == "fast" else "fast"
        return self.mode

    def describe(self) -> str:
        """One line for the log, e.g. 'Fast mode (gemini-3.5-flash-lite)'."""
        mode = MODES[self.mode]
        return f"{mode.label} mode ({mode.model})"

    # --- Replying -------------------------------------------------------

    def respond(self, text: str) -> str:
        """Send `text` and return the whole reply as one string."""
        return " ".join(self.respond_stream(text))

    def respond_stream(self, text: str):
        """
        Send `text` to Gemini and hand out E.V.E.'s reply one sentence at a time.

        This is a "generator": instead of returning once, it `yield`s each
        sentence as soon as it's ready, and whoever is looping over it gets
        that sentence straight away.
        """
        message = types.Content(role="user", parts=[types.Part(text=text)])
        said = []   # every sentence handed out, to remember at the end
        try:
            try:
                for sentence in self._sentences(message, MODES[self.mode]):
                    said.append(sentence)
                    yield sentence
            except (errors.APIError, *TIMEOUT_ERRORS) as error:
                # Think model busy or too slow? Answer with the fast one
                # instead, if we haven't started speaking yet.
                too_slow = isinstance(error, TIMEOUT_ERRORS)
                busy = too_slow or error.code in BUSY_CODES
                if self.mode == "think" and busy and not said:
                    reason = "too slow" if too_slow else f"busy, {error.code}"
                    self.on_note(f"Think model {reason}: using fast model")
                    for sentence in self._sentences(message, MODES["fast"]):
                        said.append(sentence)
                        yield sentence
                else:
                    raise
            if not said:
                said.append("I'm afraid I drew a blank there, sir.")
                yield said[-1]
        except (errors.APIError, *WEB_ERRORS) as error:
            # Anything that went wrong talking to Gemini becomes one kind of
            # error with a plain reason, so the voice knows what to do with it.
            raise BrainError(explain(error)) from error
        finally:
            # "finally" runs however this ends: finished, failed, or cut short
            # because you talked over her. She remembers whatever she said.
            if said:
                self._remember(message, " ".join(said))

    def _sentences(self, message: types.Content, mode: Mode):
        """Ask Gemini, and yield the reply as clean, speakable sentences."""
        for sentence in split_sentences(self._text_pieces(message, mode)):
            sentence = clean_for_speech(sentence)
            if sentence:
                yield sentence

    def _text_pieces(self, message: types.Content, mode: Mode):
        """
        Ask Gemini and yield her reply as it arrives, a few words at a time.

        If Gemini asks to use a tool instead of answering ("run get_weather
        for Leeds"), we run it, send back the result, and ask again. That's
        one "round". Usually there are 0 or 1 rounds before she answers.
        """
        # This list grows during the rounds: the tool requests and results are
        # added to it. They're NOT saved in her long-term history, which only
        # keeps what you said and what she said, so it stays small.
        contents = self.history + [message]
        for round_number in range(MAX_TOOL_ROUNDS + 1):
            # On the last round, don't offer tools, so she has to answer.
            offer_tools = bool(TOOLS) and round_number < MAX_TOOL_ROUNDS
            config = types.GenerateContentConfig(
                system_instruction=self.personality + situation(),
                max_output_tokens=MAX_REPLY_TOKENS,
                thinking_config=types.ThinkingConfig(thinking_level=mode.thinking),
                http_options=types.HttpOptions(timeout=mode.timeout * 1000),   # milliseconds
                # Hand Gemini our Python functions; it reads their docstrings to
                # know what each does. "disable" means it asks US to run them,
                # rather than the library running them quietly, so we can log it.
                tools=TOOLS if offer_tools else None,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            )

            reply_parts = []   # everything Gemini sent this round
            if mode.stream:
                # The reply arrives in "chunks" of a few words each.
                chunks = self.client.models.generate_content_stream(
                    model=mode.model, contents=contents, config=config)
            else:
                # Wait for the whole reply, then treat it as a single chunk.
                chunks = [self.client.models.generate_content(
                    model=mode.model, contents=contents, config=config)]
            for chunk in chunks:
                parts = (chunk.candidates and chunk.candidates[0].content
                         and chunk.candidates[0].content.parts) or []
                for part in parts:
                    reply_parts.append(part)
                    if part.text and not part.thought:   # (skip her hidden "thinking")
                        yield part.text

            tool_requests = [part.function_call for part in reply_parts if part.function_call]
            if not tool_requests:
                return   # a normal answer: we're done

            # Run each tool she asked for, and add the results to the conversation.
            # We send back Gemini's own request parts unchanged: they carry a
            # "thought signature" that Gemini needs to see again.
            contents.append(types.Content(role="model", parts=reply_parts))
            results = []
            for request in tool_requests:
                args = dict(request.args or {})
                self.on_tool(describe_tool(request.name, args))
                result = run_tool(request.name, args)
                results.append(types.Part(function_response=types.FunctionResponse(
                    id=request.id, name=request.name, response=result)))
            self.on_tool(None)   # tools finished, back to thinking
            contents.append(types.Content(role="user", parts=results))

    def _remember(self, message: types.Content, reply: str) -> None:
        self.history.append(message)
        self.history.append(types.Content(role="model", parts=[types.Part(text=reply)]))
        # Each exchange is 2 messages; keep only the most recent ones.
        self.history = self.history[-MAX_EXCHANGES * 2:]

    def forget(self) -> None:
        """Wipe the conversation memory (a fresh start)."""
        self.history.clear()


# --- What's going on right now ----------------------------------------------

def situation() -> str:
    """
    A few lines added after her personality on EVERY request, so she always
    knows the current date and time (Gemini has no clock of its own) and
    where sir lives. Made fresh each time, so the time is always right.
    """
    now = datetime.now().astimezone()   # this PC's local time and time zone
    hour = now.strftime("%I").lstrip("0")   # "03" -> "3"
    lines = [
        "",
        "",
        f"Right now it is {now:%A} {now.day} {now:%B %Y}, {hour}:{now:%M} {now:%p}".replace("AM", "am").replace("PM", "pm")
        + f" (time zone {now:%Z}).",
    ]
    home = os.getenv("EVE_HOME_CITY", "").strip()
    if home:
        lines.append(f"Sir lives in {home}. Assume he means there unless he says otherwise.")
    return "\n".join(lines)


# --- Text helpers -----------------------------------------------------------

# A sentence ends at . ! or ? followed by a space, or at a line break.
SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")
MIN_SENTENCE_CHARS = 20   # shorter bits ("Ah." / "Yes, sir.") are joined to the next one


def split_sentences(pieces):
    """
    Turn a stream of text pieces ("Hello the", "re, sir. How", " are you?")
    into whole sentences ("Hello there, sir.", "How are you?"), handing
    each one out as soon as it's complete.
    """
    buffer = ""
    for piece in pieces:
        buffer += piece
        # Cut off every complete sentence at the front of the buffer.
        while True:
            match = SENTENCE_END.search(buffer)
            if not match:
                break
            sentence = buffer[:match.start()].strip()
            # Too short? Leave it in the buffer and wait for the next sentence.
            # (A line break always counts, so bullet points don't run together.)
            if len(sentence) < MIN_SENTENCE_CHARS and "\n" not in match.group():
                next_match = SENTENCE_END.search(buffer, match.end())
                if not next_match:
                    break
                match = next_match
                sentence = buffer[:match.start()].strip()
            buffer = buffer[match.end():]
            if sentence:
                yield sentence
    if buffer.strip():
        yield buffer.strip()   # whatever is left when the reply ends


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
