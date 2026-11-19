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

She can also use tools from the actions/ folder: look-ups (weather,
Wikipedia, web search, memory, files, looking at the screen) and actions
(open apps, websites and files, timers, volume and media). Gemini decides
when a message needs one; see _text_pieces().
Anything risky asks sir first; see brain/confirm.py.

This file knows nothing about the HUD or the voice. It just turns text
into a reply, so it can be tested on its own:  .venv\\Scripts\\python -m brain
"""

import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from google import genai
from google.genai import errors, types

from brain import confirm
from brain.chat_log import get_chat_log, nice_time
from brain.commands import command_words
from brain.memory import get_memory
from brain.rate_count import get_rate_count

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
diary = logging.getLogger("eve")   # the diary in data/logs/ (see log_file.py)

# Her tools (weather, Wikipedia, web search) live in the actions/ folder.
# If that folder is missing or broken, she just works without them.
try:
    from actions import TOOLS, run_tool
    from actions import describe as describe_tool
except ImportError:
    TOOLS = []
MAX_TOOL_ROUNDS = 3   # at most this many look-ups before she must answer
# After she looks at the screen, she keeps the picture (in memory only, never on
# disk) for follow-up questions, until it's gone this long without being asked about.
SCREENSHOT_KEEP_MINUTES = 10


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


@dataclass
class Screenshot:
    """A picture of sir's screen she's keeping for follow-up questions."""
    jpeg: bytes
    taken: str          # clock time, e.g. "14:05"
    last_used: float    # when it was last sent with a question (time.monotonic())


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
        # The speech log (brain/chat_log.py). If the last chat was recent,
        # carry on from it: those chats go back into her short-term memory.
        self.chat_log = get_chat_log()
        earlier = self.chat_log.to_reload()
        for chat in earlier:
            self.history.append(types.Content(role="user", parts=[types.Part(text=chat["you"])]))
            self.history.append(types.Content(role="model", parts=[types.Part(text=chat["eve"])]))
        # How many exchanges at the start of her history are from before she
        # restarted, and when the last one was (she's told, so she doesn't
        # think sir is still on that topic).
        self.earlier = len(earlier)
        self.earlier_time = nice_time(earlier[-1]["time"]) if earlier else ""
        if earlier:
            diary.info(f"Chat log: picked up {len(earlier)} chats from earlier (last at {self.earlier_time})")
        wanted = os.getenv("EVE_BRAIN_MODE", DEFAULT_MODE).strip().lower()
        self.mode = wanted if wanted in MODES else DEFAULT_MODE
        # Something to call with short notes for the log (e.g. "think model busy").
        # The voice controller swaps this for its own log; on its own, we just print.
        self.on_note = print
        # Called with e.g. "Checking weather: Leeds" when a tool starts, and
        # with None when the tools are done. The voice uses it for the log and
        # the eye's LOOKING state. On its own, we print it.
        self.on_tool = lambda text: text and print(f"       ({text})")
        # The last look at sir's screen, kept for follow-up questions (see _with_screenshot).
        self.screenshot: Screenshot | None = None

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
        # FIRST: was she waiting for a "yes" (brain/confirm.py)? A yes does the
        # action; anything else cancels it and is then handled as usual below.
        # Checked here, in our own code before Gemini, so only sir's own
        # "yes" as his very next message can set it off.
        waiting = confirm.waiting_for()
        done_line = confirm.answer(text)
        if done_line:
            self.on_note(f"Confirmed: {waiting}")
            yield done_line
            return
        if waiting:
            self.on_note(f"Not confirmed, cancelled: {waiting}")

        # "Start fresh" / "forget that": wipe her memory instead of asking
        # Gemini. Instant, works offline, and isn't itself remembered.
        if wants_fresh_start(text):
            remembered = len(self.history) // 2
            self.forget()
            self.on_note(f"Memory cleared ({remembered} exchanges forgotten)")
            yield FRESH_START_REPLY
            return

        # "Forget everything about me": ask first, then wipe on a "yes".
        if wants_memory_wipe(text):
            count = len(get_memory())
            if count == 0:
                yield "There's nothing to forget, sir. I haven't saved anything about you yet."
                return

            def wipe() -> str:
                wiped = get_memory().forget_everything()   # (a backup copy is kept)
                self.on_note(f"Long-term memory wiped ({wiped} facts, backup in data/memory.backup.json)")
                return "Done, sir. I've forgotten everything I knew about you."

            facts = "one thing" if count == 1 else f"all {count} things"
            question = f"Just to be sure, sir: that erases {facts} I remember about you. Say yes to confirm."
            yield confirm.ask_first(question, wipe, "wipe long-term memory")["say"]
            return

        # "Clear the chat log": deletes the saved chats, so ask first too.
        if wants_log_clear(text):
            count = len(self.chat_log.all())
            if count == 0:
                yield "The chat log is already empty, sir."
                return

            def clear() -> str:
                cleared = self.chat_log.clear()
                self.history.clear()   # what's in her memory came from the log
                self.earlier = 0
                self.on_note(f"Chat log cleared ({cleared} chats)")
                return "Done, sir. The chat log is empty."

            chats = "one chat" if count == 1 else f"{count} chats"
            question = f"Just to be sure, sir: that deletes the {chats} in my chat log. Say yes to confirm."
            yield confirm.ask_first(question, clear, "clear the chat log")["say"]
            return

        # Used up this minute's free requests? Say so, rather than send one
        # that Google would refuse (which would sound like being offline).
        wait = get_rate_count().seconds_until_free()
        if wait:
            limit = get_rate_count().per_minute
            self.on_note(f"Gemini limit reached ({limit} a minute): {wait}s to wait")
            yield (f"I've used my {limit} requests for this minute, sir. "
                   f"Give me about {_round_up(wait)} seconds.")
            return

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
        # (The screenshot, if she's still keeping one, rides along with his
        # question, but never goes into her history.)
        contents = self.history + [self._with_screenshot(message)]
        # Her instructions (personality + date + memory) are made ONCE per
        # question. If she saves a fact mid-answer, she shouldn't then see it
        # in her memory and think she "already knew" it.
        instructions = self.personality + situation() + self._earlier_note()
        said = message.parts[0].text if message.parts else ""   # sir's own words, for run_tool's checks
        for round_number in range(MAX_TOOL_ROUNDS + 1):
            # On the last round, don't offer tools, so she has to answer.
            offer_tools = bool(TOOLS) and round_number < MAX_TOOL_ROUNDS
            config = types.GenerateContentConfig(
                system_instruction=instructions,
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
            get_rate_count().note()   # one more request (for the HUD's GEMINI // count)
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
            pictures = []      # screenshots from look_at_screen, sent after the results
            quick_lines = []   # each tool's ready-made "say" line, if it has one
            for request in tool_requests:
                args = dict(request.args or {})
                self.on_tool(describe_tool(request.name, args))
                result = run_tool(request.name, args, said=said)
                # A screenshot can't go in the (text-only) result, so it's
                # sent as a picture next to it. It's never put in her history
                # or the chat log; she keeps it in memory for follow-up
                # questions for a while (see _with_screenshot and actions/screen.py).
                image = result.pop("_image", None)
                if image:
                    pictures.append(types.Part.from_bytes(data=image, mime_type="image/jpeg"))
                    self._keep_screenshot(image)
                quick_lines.append(result.get("say"))
                results.append(types.Part(function_response=types.FunctionResponse(
                    id=request.id, name=request.name, response=result)))
            self.on_tool(None)   # tools finished, back to thinking

            # Quick reply: actions like "open Spotify" or "set a timer" come back
            # with a line ready to say ("Opening Spotify, sir."). If EVERY tool
            # this round has one, say those instead of asking Gemini to word the
            # answer: one request instead of two (the free plan allows 15 a minute).
            # Look-ups (weather...) have no "say" line, so Gemini still words those.
            if all(quick_lines):
                diary.info("Quick reply: no second Gemini request needed")
                for number, line in enumerate(quick_lines, start=1):
                    if number < len(quick_lines):
                        # Several actions at once: only the last line ends in "sir".
                        line = re.sub(r",? sir([.?!])$", r"\1", line)
                    yield "\n" + line   # the line break keeps each one a separate sentence
                return
            contents.append(types.Content(role="user", parts=results + pictures))

    def _remember(self, message: types.Content, reply: str) -> None:
        self.history.append(message)
        self.history.append(types.Content(role="model", parts=[types.Part(text=reply)]))
        # Each exchange is 2 messages; keep only the most recent ones.
        dropped = max(0, len(self.history) // 2 - MAX_EXCHANGES)
        self.history = self.history[-MAX_EXCHANGES * 2:]
        # Older exchanges drop off the front first, so the earlier-session ones go first.
        self.earlier = max(0, self.earlier - dropped)
        # ...and into the speech log file (brain/chat_log.py).
        self.chat_log.add(message.parts[0].text or "", reply)

    # --- Remembering the screen for follow-up questions -------------------------

    def _keep_screenshot(self, jpeg: bytes) -> None:
        """Keep the picture she just took, replacing any older one."""
        self.screenshot = Screenshot(jpeg, datetime.now().strftime("%H:%M"), time.monotonic())
        self.on_note(f"Keeping the screenshot for follow-up questions "
                     f"(memory only, gone after {SCREENSHOT_KEEP_MINUTES} quiet minutes)")

    def _with_screenshot(self, message: types.Content) -> types.Content:
        """
        Sir's message, with the kept screenshot attached in front of it, so
        "what about question 3?" works without looking again. Only what's
        sent to Gemini this time: `message` itself (which goes into her
        history and the chat log) is left as it was.
        """
        shot = self.screenshot
        if shot is None:
            return message
        if time.monotonic() - shot.last_used > SCREENSHOT_KEEP_MINUTES * 60:
            self.forget_screenshot(f"not asked about for {SCREENSHOT_KEEP_MINUTES} minutes")
            return message
        shot.last_used = time.monotonic()
        note = (f"(This is the picture of sir's screen you took at {shot.taken}. Use it if his "
                "message is about what's on his screen. If he says it's changed, or asks you to "
                "look again, use look_at_screen for a new one.)")
        return types.Content(role="user", parts=[
            types.Part.from_bytes(data=shot.jpeg, mime_type="image/jpeg"),
            types.Part(text=note), *message.parts])

    def forget_screenshot(self, why: str) -> None:
        if self.screenshot is not None:
            self.screenshot = None
            self.on_note(f"Screenshot forgotten ({why})")

    def _earlier_note(self) -> str:
        """Tell her which chats are from before she restarted, if any are left."""
        if not self.earlier:
            return ""
        return (f"\n\nThe first {self.earlier} exchanges of this conversation are from an "
                f"earlier session (the last one at {self.earlier_time}), before you were "
                "restarted. Sir may have moved on to something else: don't assume he's "
                "still on that topic, and don't bring it up unless he does.")

    def forget(self) -> None:
        """Wipe the conversation memory (a fresh start)."""
        self.history.clear()
        self.earlier = 0
        self.forget_screenshot("fresh start")
        # The log keeps the chats to read, but they won't be reloaded at start-up.
        self.chat_log.mark_fresh_start()


# --- "Start fresh" ----------------------------------------------------------

# Say (or type) any of these on its own, and she forgets the conversation so far.
# Add your own here; write them in lower case, without punctuation.
FRESH_START_PHRASES = {
    "start fresh", "start afresh", "fresh start", "start over", "start again",
    "forget that", "forget it", "forget everything", "forget all that",
    "clear your memory", "wipe your memory", "reset your memory",
    "new conversation", "new topic", "clean slate",
}
FRESH_START_REPLY = "Clean slate, sir."
# (command_words() trims polite words and punctuation; it's in brain/commands.py.)


def wants_fresh_start(text: str) -> bool:
    """
    True if `text` is just a "start fresh" command, like "Start fresh." or
    "Eve, forget that please". Only the WHOLE message counts, so "forget that
    I'm vegetarian, I'm not" is treated as a normal message, not a reset.
    """
    return command_words(text) in FRESH_START_PHRASES


# "Forget everything about me": wipes her LONG-TERM memory (data/memory.json),
# not just the conversation. Because that's hard to undo, she asks first
# (brain/confirm.py), and only a "yes" as the very next message does it.
MEMORY_WIPE_PHRASES = {
    "forget everything about me", "forget everything you know about me",
    "forget all about me", "forget all you know about me", "forget me",
    "wipe your memory of me", "erase your memory of me", "erase everything about me",
    "delete everything you know about me", "delete everything about me",
    "clear your long term memory", "wipe your long term memory",
}


def wants_memory_wipe(text: str) -> bool:
    return command_words(text) in MEMORY_WIPE_PHRASES


# "Clear the chat log": deletes data/chat_log.json's chats (asks first).
LOG_CLEAR_PHRASES = {
    "clear the log", "clear your log", "clear the chat log", "clear your chat log",
    "delete the chat log", "delete your chat log", "wipe the chat log", "wipe your chat log",
    "empty the chat log", "clear the speech log", "delete the speech log", "wipe the speech log",
    "clear chat history", "clear the chat history", "delete the chat history",
}


def _round_up(seconds: int) -> int:
    """Round up to the next 5 seconds, so she says "about 20", not "about 17"."""
    return max(5, -(-seconds // 5) * 5)


def wants_log_clear(text: str) -> bool:
    return command_words(text) in LOG_CLEAR_PHRASES


# --- What's going on right now ----------------------------------------------

def situation() -> str:
    """
    A few lines added after her personality on EVERY request, so she always
    knows the current date and time (Gemini has no clock of its own), where
    sir lives, and what she remembers about him. Made fresh each time.
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

    # Her long-term memory (data/memory.json), read fresh every time, so a
    # fact saved a moment ago is already known in the very next answer.
    facts = get_memory().as_text()
    lines.append("")
    lines.append("What you remember about sir from earlier conversations (your long-term memory, numbered):")
    lines.append(facts or "(nothing yet)")
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
