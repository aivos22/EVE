"""
The voice "conductor": joins hearing, thinking and speaking together.

    Space down  -> start recording
    Space up    -> transcribe -> ask the brain (or echo) -> speak the reply

All the slow work (loading models, transcribing, speaking) happens on a
background thread, so the HUD never freezes. The controller never
touches the window directly. It only sends out signals, and main.py
connects those to the log feed and the caption.
"""

import queue
import threading

from PySide6.QtCore import QObject, Signal

from ui.eye_state import EyeState
from voice.stt import SpeechToText
from voice.tts import TextToSpeech


def find_brain():
    """
    Look for a `respond(text) -> reply` function in the brain/ folder.
    Returns it if found, or None (which means echo mode).
    """
    try:
        from brain import respond
        return respond
    except ImportError:
        return None


class VoiceController(QObject):
    # Signals: Qt safely carries these from the background thread to the window.
    log = Signal(str, str)     # (message, source), e.g. ("Heard: hi", "VOICE")
    caption = Signal(str, str) # (who, text): who is "you" or "eve"; empty text clears it
    ready = Signal()           # models loaded, Space will work now
    state = Signal(EyeState)   # what the eye should be doing
    level = Signal(float)      # her voice loudness 0-1, many times a second while speaking

    def __init__(self, parent=None):
        super().__init__(parent)
        self.stt: SpeechToText | None = None
        self.tts: TextToSpeech | None = None
        self.brain = find_brain()
        self.status = "loading"   # loading / idle / recording / working / speaking
        self._jobs: queue.Queue = queue.Queue()
        self._worker = threading.Thread(target=self._run_jobs, daemon=True)

    # --- Starting and stopping ------------------------------------------

    def start(self) -> None:
        """Start the background thread and load the speech models on it."""
        self._worker.start()
        self._jobs.put(self._load)

    def shutdown(self) -> None:
        """Called when E.V.E. closes: stop talking and free the microphone."""
        if self.tts:
            self.tts.stop()
        self._jobs.put(None)   # tells the worker loop to finish
        if self.stt:
            self.stt.shutdown()

    # --- Push-to-talk (called from the window, on the main thread) ------

    def talk_pressed(self) -> None:
        if self.status == "loading":
            self.log.emit("Still loading, one moment...", "VOICE")
            return
        if self.status == "working":
            return   # still transcribing the last thing you said
        if self.status == "speaking":
            self.tts.stop()   # you talked over her: she stops and listens
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
        mode = "brain connected" if self.brain else "echo mode (no brain yet)"
        self.log.emit(f"Ready, {mode}. Hold Space to talk", "VOICE")
        self.ready.emit()
        self._back_to_idle()

    def _handle_speech(self) -> None:
        text = self.stt.stop_and_transcribe()
        if not text:
            self.log.emit("Didn't catch that", "VOICE")
            self.caption.emit("you", "")
            self._back_to_idle()
            return
        self.caption.emit("you", text)
        self.log.emit(f"Heard: {text}", "VOICE")

        reply = self.brain(text) if self.brain else text   # echo mode: say it back
        # Make the audio first (the eye stays on THINKING while it downloads)...
        audio_path, source = self.tts.prepare(reply)
        # ...then show the reply and speak it.
        self.caption.emit("eve", reply)
        self.log.emit(f"Speaking ({source})", "TTS")
        self.status = "speaking"
        self.state.emit(EyeState.SPEAKING)
        # on_level gets her loudness for every little chunk of audio: that's the pulse.
        self.tts.play(audio_path, on_level=self.level.emit)
        if self.status == "speaking":   # (not interrupted by a new Space press)
            self._back_to_idle()

    def _back_to_idle(self) -> None:
        self.status = "idle"
        self.state.emit(EyeState.IDLE)
