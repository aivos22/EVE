"""
The voice "conductor": joins hearing, thinking and speaking together.

    Space down  -> start recording
    Space up    -> transcribe -> ask the brain (or echo) -> speak the reply

Or, with the wake word on, just say "Eve, ..." (see voice/wake_words.py).
A third thread (the "listener") waits for speech while she's idle, and
only passes on what was said to her by name. After she answers, she
listens for a follow-up for FOLLOW_UP_SECONDS without needing her name.

When a timer goes off (actions/timers.py), she says so: "Sir, your pasta
timer is done." The announcement joins the same queue as her replies, so
if she's in the middle of saying something, it waits until she's finished.

Her reply is spoken sentence by sentence, like an assembly line:

    brain:    [sentence 1][sentence 2][sentence 3]
    voice:          [audio 1]  [audio 2]  [audio 3]
    speaker:                [plays 1]  [plays 2]  [plays 3]

A helper thread (the "maker") turns each sentence into audio as soon as
the brain hands it over, and drops it in a queue. The main background
thread (the "worker") takes them out and plays them in order. So she
starts talking after ONE sentence is ready, not the whole answer.

All the slow work happens on background threads, so the HUD never
freezes. The controller never touches the window directly. It only
sends out signals, and main.py connects those to the HUD.
"""

import logging
import os
import queue
import threading
import time
import wave

from PySide6.QtCore import QObject, Signal

from ui.eye_state import EyeState
from voice.microphone import check_microphone
from voice.stt import SpeechToText
from voice.tts import TextToSpeech
from voice import wake_words

# The diary (data/logs/), for full details of problems. See log_file.py.
diary = logging.getLogger("eve")

READY_AHEAD = 3   # how many sentences the maker may get ready before she says them
# What she says when the brain can't be reached. It's made once at start-up
# and saved in the phrase cache, so it plays even with no internet.
OFFLINE_LINE = "I can't reach my systems right now, sir."
# What she says at start-up if she has no microphone.
NO_MIC_LINE = "I can't hear you at the moment, sir. Press slash to type to me instead."
# After she answers someone who used her name, how long she keeps listening
# for another question without needing to hear "Eve" again.
FOLLOW_UP_SECONDS = 8
# How long she waits after she stops talking before listening again, so the
# last echo of her own voice from the speakers isn't picked up.
QUIET_AFTER_SPEAKING = 0.6


class BrainError(Exception):
    """Stand-in used only when there's no brain/ folder (so nothing can raise it)."""


def audio_seconds(wav_path) -> float:
    """How long a .wav file lasts, in seconds (0 if it can't be read)."""
    try:
        with wave.open(str(wav_path)) as wav:
            return wav.getnframes() / wav.getframerate()
    except (OSError, wave.Error):
        return 0.0


def find_brain():
    """
    Look for the brain/ folder's get_brain() function.
    Returns it if found, or None (which means echo mode).
    """
    global BrainError
    try:
        from brain import BrainError, get_brain   # noqa: F811  (swap in the real BrainError)
        return get_brain
    except ImportError:
        return None


class VoiceController(QObject):
    # Signals: Qt safely carries these from the background thread to the window.
    log = Signal(str, str)     # (message, source), e.g. ("Heard: hi", "VOICE")
    caption = Signal(str, str) # (who, text): who is "you" or "eve"; empty text clears it
    subtitle = Signal(str, float)  # (sentence, seconds): her sentence, typed out over that long
    ready = Signal()           # models loaded, Space will work now
    state = Signal(EyeState)   # what the eye should be doing
    level = Signal(float)      # her voice loudness 0-1, many times a second while speaking
    mode_changed = Signal(str) # the brain's mode label, "FAST" or "THINK"
    wake_changed = Signal(bool)    # wake word switched on (True) or off (False)
    shutdown_requested = Signal()  # "Eve, shut down": the window should close
    hide_requested = Signal()      # "Eve, hide": take the display off screen (she keeps running)
    show_requested = Signal()      # "Eve, show yourself": bring the display back
    timer_done = Signal(str)   # a timer went off, e.g. "pasta timer": the eye should flash

    def __init__(self, timers=None, parent=None):
        """`timers` is the timer keeper (actions/timers.py), if there is one."""
        super().__init__(parent)
        if timers is not None:
            # Called on the timer keeper's own thread. All we do there is send
            # a signal and add a job to the queue, both safe from any thread.
            timers.when_set(self._timer_set)
            timers.when_done(self._timer_went_off)
        self.stt: SpeechToText | None = None
        self.tts: TextToSpeech | None = None
        self._get_brain = find_brain()
        self.brain = None          # made in _load, once .env has been read
        self._brain_problem = ""   # why the brain couldn't start, if it couldn't
        self._mic_problem = ""     # why she can't hear, if she can't
        self._mic_retrying = False # True while re-checking the microphone
        self.status = "loading"    # loading / idle / recording / working / speaking
        self._jobs: queue.Queue = queue.Queue()
        self._worker = threading.Thread(target=self._run_jobs, daemon=True)
        self._cancel = threading.Event()   # set = "stop the current reply now"
        # Wake word: on unless EVE_WAKE_WORD=off in .env. W switches it.
        self.wake_on = os.getenv("EVE_WAKE_WORD", "on").strip().lower() not in ("off", "no", "false", "0")
        self._listener = threading.Thread(target=self._listen_for_wake, daemon=True)
        self._stop_overhearing = threading.Event()  # set = "stop listening for her name now"
        self._closing = threading.Event()
        self._idle_since = 0.0     # when she last went idle (time.time())
        self._awake_until = 0.0    # listening without her name until this time
        self._follow_up = False    # True = open the follow-up window after this reply

    # --- Starting and stopping ------------------------------------------

    def start(self) -> None:
        """Start the background thread and load the speech models on it."""
        self._worker.start()
        self._listener.start()
        self._jobs.put(self._load)

    def shutdown(self) -> None:
        """Called when E.V.E. closes: stop talking and free the microphone."""
        self._closing.set()
        self._stop_overhearing.set()
        self._cancel.set()
        if self.tts:
            self.tts.stop()
        self._jobs.put(None)   # tells the worker loop to finish
        if self.stt:
            self.stt.shutdown()

    # --- Controls (called from the window, on the main thread) ----------

    def talk_pressed(self) -> None:
        if self.status == "loading":
            self.log.emit("Still loading, one moment...", "VOICE")
            return
        if self.status == "working":
            return   # still transcribing or thinking about the last thing you said
        if self.stt is None:
            # No microphone. Check again in the background (it may have been
            # plugged in since); until then, typing with / still works.
            if not self._mic_retrying:
                self._mic_retrying = True
                self.log.emit(f"Can't hear: {self._mic_problem}", "VOICE")
                self._jobs.put(self._retry_hearing)
            return
        if self.status == "speaking":
            # You talked over her: she stops, and drops the sentences she hadn't said.
            self._cancel.set()
            self.tts.stop()
        self.status = "recording"
        self._follow_up = False
        self._awake_until = 0.0
        # If the listener is waiting for her name, make it let go of the mic first.
        self.stt.stop_listening(self._stop_overhearing)
        self.stt.start()
        self.state.emit(EyeState.LISTENING)
        self.caption.emit("you", "")
        self.log.emit("Listening...", "VOICE")

    def talk_released(self) -> None:
        if self.status != "recording":
            return
        self.status = "working"
        self.state.emit(EyeState.THINKING)
        self._jobs.put(self._handle_speech)

    def typed(self, text: str) -> None:
        """
        A message from the typed command bar. From here it goes down exactly
        the same path as speech (think, then speak), just without the microphone.
        """
        if self.status == "loading":
            self.log.emit("Still loading, one moment...", "VOICE")
            return
        if self.status in ("working", "recording"):
            self.log.emit("Busy, try again in a moment", "VOICE")
            return
        if self.status == "speaking":
            self._cancel.set()   # a new message interrupts her, like talking over her
            self.tts.stop()
        self.status = "working"
        self._stop_overhearing.set()   # so she doesn't record her own reply
        self._follow_up = False
        self._awake_until = 0.0
        self.state.emit(EyeState.THINKING)
        self.caption.emit("you", text)
        self.log.emit(f"Typed: {text}", "TEXT")
        # Run on the background thread, like everything slow.
        self._jobs.put(lambda: self._reply_to(text))

    def toggle_mode(self) -> None:
        """Switch the brain between fast mode and think mode."""
        if not self.brain:
            self.log.emit("No brain connected, so no modes to switch", "BRAIN")
            return
        self.brain.toggle_mode()
        self.log.emit(f"Switched to {self.brain.describe()}", "BRAIN")
        self.mode_changed.emit(self.brain.mode.upper())

    def toggle_wake(self) -> None:
        """Switch the wake word on or off (W key)."""
        self.wake_on = not self.wake_on
        if not self.wake_on:
            self._stop_overhearing.set()
            self._awake_until = 0.0
        if self.wake_on:
            self.log.emit('Wake word on: say "Eve"', "VOICE")
        else:
            self.log.emit("Wake word off: hold Space to talk", "VOICE")
        self.wake_changed.emit(self.wake_on)

    # --- Work done on the background thread -----------------------------

    def _run_jobs(self) -> None:
        """The background thread: take jobs off the queue and run them, one at a time."""
        while True:
            job = self._jobs.get()
            if job is None:
                break
            try:
                job()
            except Exception as error:   # keep the thread alive whatever happens
                self.log.emit(f"Error: {error}", "VOICE")
                diary.exception("Voice job failed")   # full details, for the diary file
                self._back_to_idle()

    def _load(self) -> None:
        try:
            # Her voice first: even with no microphone she can still talk
            # (and you can still type to her).
            self.tts = TextToSpeech()
            self.log.emit(self.tts.describe(), "TTS")
            for note in self.tts.notes:   # e.g. why ElevenLabs isn't being used
                self.log.emit(note, "TTS")
            self._load_hearing()
            self._connect_brain()
            self._finish_loading()
        finally:
            # Whatever happened above, tell the HUD loading is over, so the
            # eye never gets stuck on BOOTING.
            self.ready.emit()
            if self.status == "loading":
                self._back_to_idle()

    def _load_hearing(self) -> bool:
        """
        Check the microphone, then load the speech-to-text models.
        Returns True if she can hear. If not, she carries on without it.
        """
        problem = check_microphone()
        if problem is None:
            self.log.emit("Loading speech models...", "VOICE")
            try:
                self.stt = SpeechToText(on_live_text=self._live_caption)
                self._mic_problem = ""
                return True
            except Exception as error:
                problem = f"speech recognition failed to load ({type(error).__name__})"
                diary.exception("Speech-to-text failed to load")
        self.stt = None
        self._mic_problem = problem
        self.log.emit(f"Can't hear: {problem}", "VOICE")
        diary.warning(f"No hearing: {problem}")
        return False

    def _live_caption(self, text: str) -> None:
        """The rough "so far" text while someone talks. Only shown if it's for her,
        so chatter in the room doesn't appear while she waits for her name."""
        if self.status == "recording" or self._awake_until > time.time():
            self.caption.emit("you", text)

    def _finish_loading(self) -> None:
        """Stock phrases, then the "ready" message."""
        # Make her stock phrases now, while we're probably online, so they're
        # saved in the cache: instant to say, and they work with no internet.
        from actions.timers import announcement_for
        lines = [wake_words.WAKE_REPLY, wake_words.SLEEP_REPLY, wake_words.SHUTDOWN_REPLY,
                 announcement_for("")]   # "Sir, your timer is done."
        if self._get_brain:
            from brain.gemini_brain import FRESH_START_REPLY
            lines += [OFFLINE_LINE, FRESH_START_REPLY]
        for line in lines:
            try:
                self.tts.prepare(line)
            except Exception:
                pass   # not worth failing start-up over; she'll try again when needed
        mode = "brain connected" if self.brain else "echo mode" if not self._get_brain else "brain offline"
        self.wake_changed.emit(self.wake_on)
        if self.stt:
            how = 'Say "Eve" or hold Space' if self.wake_on else "Hold Space to talk"
            self.log.emit(f"Ready, {mode}. {how}", "VOICE")
            return
        # No hearing: say so out loud once, and point to the command bar.
        self.log.emit(f"Ready, {mode}. Typing only: press /", "VOICE")
        self.ready.emit()      # the HUD can leave BOOTING before she speaks
        self._back_to_idle()   # (so typing works even while she's saying this)
        self._speak([NO_MIC_LINE])   # goes back to idle by itself when done

    def _retry_hearing(self) -> None:
        """Space pressed with no microphone: look again (maybe it's plugged in now)."""
        self.log.emit("Checking the microphone again...", "VOICE")
        if self._load_hearing():
            self.log.emit("Microphone found. Hold Space to talk", "VOICE")
        else:
            self.log.emit("Still no microphone. Press / to type", "VOICE")
        self._mic_retrying = False

    def _connect_brain(self) -> None:
        if not self._get_brain:
            return
        try:
            self.brain = self._get_brain()
        except Exception as error:   # e.g. no API key in .env
            self._brain_problem = str(error)
            self.log.emit(f"Brain off: {error}", "BRAIN")
            diary.warning(f"Brain could not start: {error}")
            return
        self.brain.on_note = lambda note: self.log.emit(note, "BRAIN")
        self.brain.on_tool = self._tool_update
        self.log.emit(self.brain.describe() + ". M to switch", "BRAIN")
        self.mode_changed.emit(self.brain.mode.upper())

    def _tool_update(self, text: str | None) -> None:
        """
        The brain calls this when it starts using a tool ("Checking weather:
        Leeds") and with None when it's done. The eye looks around while
        she's looking something up, then goes back to thinking.
        (Runs on the maker thread; signals carry it safely to the HUD.)
        """
        if self._cancel.is_set():
            return   # you've interrupted; don't change the eye back
        if text:
            self.log.emit(text, "ACTION")
            self.state.emit(EyeState.LOOKING)
        else:
            self.state.emit(EyeState.THINKING)

    def _handle_speech(self) -> None:
        text = self.stt.stop_and_transcribe()
        if not text:
            self.log.emit("Didn't catch that", "VOICE")
            self.caption.emit("you", "")
            self._back_to_idle()
            return
        self.caption.emit("you", text)
        self.log.emit(f"Heard: {text}", "VOICE")
        self._reply_to(text)

    # --- The wake word (runs on the listener thread) -----------------------

    def _can_overhear(self) -> bool:
        """True when the listener may wait for her name: wake word on, she can
        hear, she's idle, and she finished talking a moment ago."""
        return (self.wake_on and self.stt is not None and self.status == "idle"
                and not self._closing.is_set()
                and time.time() - self._idle_since >= QUIET_AFTER_SPEAKING)

    def _listen_for_wake(self) -> None:
        """
        The listener thread. While she's idle, wait for someone to say
        something, then decide if it was for her:
          - in the follow-up window: everything counts
          - otherwise: only if it starts or ends with her name
        """
        while not self._closing.is_set():
            if not self._can_overhear():
                time.sleep(0.1)
                continue
            self._stop_overhearing.clear()
            if not self._can_overhear():
                continue   # something started in that instant; check again
            awake = self._awake_until > time.time()
            try:
                text = self.stt.listen_for_phrase(
                    self._stop_overhearing, until=self._awake_until if awake else None)
            except Exception:
                if self._closing.is_set():
                    return
                diary.exception("Listening for the wake word failed")
                time.sleep(1)
                continue
            if self._stop_overhearing.is_set() or self.status != "idle":
                continue   # Space, typing or closing took over; ignore what was heard
            if not text:
                if awake and time.time() >= self._awake_until:
                    # Nobody asked a follow-up: back to waiting for her name.
                    self._awake_until = 0.0
                    self.caption.emit("you", "")
                    self.state.emit(EyeState.IDLE)
                continue
            in_window = awake and self.stt.last_phrase_started <= self._awake_until
            request = wake_words.split_wake(text)
            if request is None:
                if not in_window:
                    diary.debug(f"Overheard (not for her): {text}")
                    continue
                request = text   # a follow-up doesn't need her name
            self._awake_until = 0.0
            # It's for her: from here it's the same path as push-to-talk.
            self.status = "working"
            self.state.emit(EyeState.THINKING)
            self.caption.emit("you", text)
            self.log.emit(f"Heard: {text}", "VOICE")
            self._jobs.put(lambda r=request: self._reply_to(r, by_name=True))

    # --- Timers (called on the timer keeper's thread) ----------------------

    def _timer_set(self, timer) -> None:
        """
        A timer was just set. Get its announcement ready NOW, while we're
        probably online, so it's saved in the phrase cache: instant when the
        timer goes off, even with no internet. It's a queued job, so it never
        holds up what she's saying.
        """
        text = timer.announcement()

        def prepare() -> None:
            if self.tts:
                try:
                    self.tts.prepare(text)
                except Exception:
                    pass   # it'll be made when needed instead
        self._jobs.put(prepare)

    def _timer_went_off(self, timer) -> None:
        """Flash the eye and log it straight away; say it when she's free."""
        self.timer_done.emit(timer.name())
        self.log.emit(f"{timer.name().capitalize()} done", "TIMER")
        self._jobs.put(lambda: self._announce(timer.announcement()))

    def _announce(self, text: str) -> None:
        """
        Say a timer announcement (on the worker thread). Because it's a job,
        it only starts once she's finished whatever she was saying.
        """
        if self._closing.is_set():
            return
        # Sir is holding Space and talking: don't talk over him.
        while self.status == "recording" and not self._closing.is_set():
            time.sleep(0.1)
        if self.status == "working":
            # He's just finished talking, and her answer is queued behind this
            # job. Go to the back of the queue, so she answers him first.
            self._jobs.put(lambda: self._announce(text))
            return
        self.status = "working"
        self._stop_overhearing.set()   # so she doesn't hear herself
        self._follow_up = False        # an announcement doesn't wait for a reply
        self._awake_until = 0.0
        self.caption.emit("you", "")
        self._speak([text])            # goes back to idle by itself when done

    # --- Replying ---------------------------------------------------------

    def _reply_to(self, text: str, by_name: bool = False) -> None:
        """
        Get the brain's reply and speak it. If the brain fails, say so politely.
        `by_name` = she was woken by her name, so she listens for a follow-up after.
        """
        # Her own commands first: no brain needed, and they work offline.
        if wake_words.wants_shutdown(text):
            self.log.emit("Shutdown requested", "VOICE")
            self._speak([wake_words.SHUTDOWN_REPLY])
            self.shutdown_requested.emit()
            return
        if wake_words.wants_hide(text):
            self.log.emit("Hiding the display", "VOICE")
            self.hide_requested.emit()   # (signals reach the window safely from this thread)
            self._speak([wake_words.HIDE_REPLY])
            return
        if wake_words.wants_show(text):
            self.log.emit("Showing the display", "VOICE")
            self.show_requested.emit()
            self._speak([wake_words.SHOW_REPLY])
            return
        if wake_words.wants_sleep(text):
            self._speak([wake_words.SLEEP_REPLY])   # no follow-up window: she's done
            return
        self._follow_up = by_name and self.wake_on
        if not text:
            # Just her name: she answers and waits for the actual question.
            self._speak([wake_words.WAKE_REPLY])
            return
        if self.brain:
            sentences = self.brain.respond_stream(text)
        elif self._get_brain:
            # There is a brain, but it couldn't start (e.g. no API key).
            self.log.emit(f"Can't reach Gemini: {self._brain_problem}", "BRAIN")
            sentences = [OFFLINE_LINE]
        else:
            sentences = [text]   # echo mode: no brain/ folder, so say it back

        failure = self._speak(sentences)
        if isinstance(failure, BrainError):
            # No internet, bad key, Gemini down... Log the reason, then say the
            # saved line instead (unless you've already talked over her).
            self.log.emit(f"Can't reach Gemini: {failure}", "BRAIN")
            # The diary gets the original technical error too, for working out why.
            diary.warning(f"Brain failed: {failure} ({failure.__cause__!r})")
            if not self._cancel.is_set():
                failure = self._speak([OFFLINE_LINE])
        if failure:
            raise failure   # anything else (e.g. no voice works): _run_jobs logs it

    def _speak(self, sentences):
        """
        Speak `sentences` one by one, as soon as each is ready.
        Returns the error if something failed along the way, otherwise None.
        """
        # Each reply gets its own "stop" flag. If you interrupt, this reply's
        # maker sees it and stops, without affecting the next reply.
        cancel = threading.Event()
        self._cancel = cancel
        ready: queue.Queue = queue.Queue(maxsize=READY_AHEAD)
        maker = threading.Thread(target=self._make_audio, args=(sentences, ready, cancel), daemon=True)
        maker.start()

        spoken = []
        failure = None
        while True:
            if cancel.is_set():
                return None           # interrupted: stop now; the maker tidies up by itself
            try:
                item = ready.get(timeout=0.1)   # check for an interruption 10 times a second
            except queue.Empty:
                continue
            if item is None:          # the maker has finished
                break
            if isinstance(item, Exception):
                failure = item        # the brain or voice failed; keep emptying the queue
                continue
            sentence, audio_path, source = item
            if not spoken:            # first sentence: she starts talking
                self.log.emit(f"Speaking ({source})", "TTS")
                self.status = "speaking"
            # Every sentence, in case a look-up between sentences changed the eye.
            # (Setting the state it's already in does nothing.)
            self.state.emit(EyeState.SPEAKING)
            spoken.append(sentence)
            # Type the sentence out while she says it. It finishes a little
            # before the audio does (90%), which reads more naturally.
            self.subtitle.emit(sentence, 0.9 * audio_seconds(audio_path))
            # on_level gets her loudness for every little chunk of audio: that's the pulse.
            self.tts.play(audio_path, on_level=self.level.emit)

        if failure:
            return failure            # _reply_to decides what to do about it
        if not cancel.is_set() and self.status in ("speaking", "working"):
            self._back_to_idle()
        return None

    def _make_audio(self, sentences, ready: queue.Queue, cancel: threading.Event) -> None:
        """
        The maker (its own thread): turn each sentence into audio and pass it on.
        `ready` has a size limit, so if she's READY_AHEAD sentences ahead,
        it waits until she has said one.
        """
        def hand_over(item) -> None:
            # Wait for room in the queue, but give up if this reply is cancelled
            # (nobody would ever take the item out, and we'd wait forever).
            while not cancel.is_set():
                try:
                    ready.put(item, timeout=0.1)
                    return
                except queue.Full:
                    pass

        try:
            for sentence in sentences:
                if cancel.is_set():
                    break
                audio_path, source = self.tts.prepare(sentence)
                hand_over((sentence, audio_path, source))
        except Exception as error:
            hand_over(error)
        finally:
            if hasattr(sentences, "close"):
                sentences.close()   # tell the brain we're done, so it remembers what was said
            hand_over(None)

    def _back_to_idle(self) -> None:
        self._idle_since = time.time()
        if self._follow_up and self.wake_on and self.stt:
            # She was asked by name: keep listening for a follow-up for a few
            # seconds (the clock starts after the quiet gap), eye in LISTENING.
            self._follow_up = False
            self._awake_until = time.time() + QUIET_AFTER_SPEAKING + FOLLOW_UP_SECONDS
            self.status = "idle"
            self.state.emit(EyeState.LISTENING)
            return
        self._follow_up = False
        self.status = "idle"
        self.state.emit(EyeState.IDLE)
