"""
The voice "conductor": joins hearing, thinking and speaking together.

    Space down  -> start recording
    Space up    -> transcribe -> ask the brain (or echo) -> speak the reply

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

import queue
import threading

from PySide6.QtCore import QObject, Signal

from ui.eye_state import EyeState
from voice.stt import SpeechToText
from voice.tts import TextToSpeech

READY_AHEAD = 3   # how many sentences the maker may get ready before she says them
# What she says when the brain can't be reached. It's made once at start-up
# and saved in the phrase cache, so it plays even with no internet.
OFFLINE_LINE = "I can't reach my systems right now, sir."


class BrainError(Exception):
    """Stand-in used only when there's no brain/ folder (so nothing can raise it)."""


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
    ready = Signal()           # models loaded, Space will work now
    state = Signal(EyeState)   # what the eye should be doing
    level = Signal(float)      # her voice loudness 0-1, many times a second while speaking
    mode_changed = Signal(str) # the brain's mode label, "FAST" or "THINK"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.stt: SpeechToText | None = None
        self.tts: TextToSpeech | None = None
        self._get_brain = find_brain()
        self.brain = None          # made in _load, once .env has been read
        self._brain_problem = ""   # why the brain couldn't start, if it couldn't
        self.status = "loading"    # loading / idle / recording / working / speaking
        self._jobs: queue.Queue = queue.Queue()
        self._worker = threading.Thread(target=self._run_jobs, daemon=True)
        self._cancel = threading.Event()   # set = "stop the current reply now"

    # --- Starting and stopping ------------------------------------------

    def start(self) -> None:
        """Start the background thread and load the speech models on it."""
        self._worker.start()
        self._jobs.put(self._load)

    def shutdown(self) -> None:
        """Called when E.V.E. closes: stop talking and free the microphone."""
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
        if self.status == "speaking":
            # You talked over her: she stops, and drops the sentences she hadn't said.
            self._cancel.set()
            self.tts.stop()
        self.status = "recording"
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

    def toggle_mode(self) -> None:
        """Switch the brain between fast mode and think mode."""
        if not self.brain:
            self.log.emit("No brain connected, so no modes to switch", "BRAIN")
            return
        self.brain.toggle_mode()
        self.log.emit(f"Switched to {self.brain.describe()}", "BRAIN")
        self.mode_changed.emit(self.brain.mode.upper())

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
                self._back_to_idle()

    def _load(self) -> None:
        self.log.emit("Loading speech models...", "VOICE")
        self.stt = SpeechToText(on_live_text=lambda text: self.caption.emit("you", text))
        self.tts = TextToSpeech()
        self.log.emit(self.tts.describe(), "TTS")
        for note in self.tts.notes:   # e.g. why ElevenLabs isn't being used
            self.log.emit(note, "TTS")
        self._connect_brain()
        if self._get_brain:
            # Make her "can't reach my systems" line now, while we're probably
            # online, so it's saved in the cache and plays even with no internet.
            try:
                self.tts.prepare(OFFLINE_LINE)
            except Exception:
                pass   # not worth failing start-up over; she'll try again when needed
        mode = "brain connected" if self.brain else "echo mode" if not self._get_brain else "brain offline"
        self.log.emit(f"Ready, {mode}. Hold Space to talk", "VOICE")
        self.ready.emit()
        self._back_to_idle()

    def _connect_brain(self) -> None:
        if not self._get_brain:
            return
        try:
            self.brain = self._get_brain()
        except Exception as error:   # e.g. no API key in .env
            self._brain_problem = str(error)
            self.log.emit(f"Brain off: {error}", "BRAIN")
            return
        self.brain.on_note = lambda note: self.log.emit(note, "BRAIN")
        self.log.emit(self.brain.describe() + ". M to switch", "BRAIN")
        self.mode_changed.emit(self.brain.mode.upper())

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

    def _reply_to(self, text: str) -> None:
        """Get the brain's reply and speak it. If the brain fails, say so politely."""
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
                self.state.emit(EyeState.SPEAKING)
            spoken.append(sentence)
            self.caption.emit("eve", " ".join(spoken))
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
        self.status = "idle"
        self.state.emit(EyeState.IDLE)
