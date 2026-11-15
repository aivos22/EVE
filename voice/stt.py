"""
Speech-to-text: turns your voice into text with Whisper (via RealtimeSTT).

Two ways to use it:

  Push-to-talk: call start() when the talk key goes down and
  stop_and_transcribe() when it comes up.

  Always listening: listen_for_phrase() waits until someone starts
  talking, records until they stop, and returns what they said. The
  wake word ("Eve") is checked by the voice controller, not here.

While you're talking, an optional `on_live_text` function gets called
with a rough "so far" transcript, for the live caption.

All models are downloaded into MODELS_DIR (not your user cache), so
E.V.E. can be copied to a memory stick with everything she needs.
"""

import logging
import os
import threading
import time

from paths import MODELS_DIR

# Tell the libraries RealtimeSTT uses where to keep their downloads.
# This MUST happen before RealtimeSTT is imported, so it's at the top.
WHISPER_DIR = MODELS_DIR / "whisper"
os.environ.setdefault("HF_HOME", str(MODELS_DIR / "huggingface"))
os.environ.setdefault("TORCH_HOME", str(MODELS_DIR / "torch"))

import torch  # noqa: E402  (imported after the settings above on purpose)
from RealtimeSTT import AudioToTextRecorder  # noqa: E402

FINAL_MODEL = "base.en"  # accurate model for the final transcript
LIVE_MODEL = "tiny.en"   # small, fast model for the live caption while you talk

# A "hint" Whisper reads before listening. Mentioning Eve here makes it expect
# that name, so "Hi Eve" stops coming out as "Hive" or "I ease".
# Add other names or words it gets wrong to this sentence.
HINT = "Eve is my AI assistant. Hi Eve. Hey Eve. Thanks Eve."


class SpeechToText:
    def __init__(self, on_live_text=None):
        """
        Loads the models. This takes a few seconds (and downloads them the
        first time), so the voice controller will call it in the background.
        """
        WHISPER_DIR.mkdir(parents=True, exist_ok=True)
        # Use the graphics card if there's a CUDA one, otherwise the CPU.
        device = "cuda" if torch.cuda.is_available() else "cpu"
        # int8 = smaller, faster maths on a CPU; float16 is the fast option on a GPU.
        compute_type = "float16" if device == "cuda" else "int8"

        self._recorder = AudioToTextRecorder(
            model=FINAL_MODEL,
            download_root=str(WHISPER_DIR),
            device=device,
            compute_type=compute_type,
            language="en",
            initial_prompt=HINT,
            initial_prompt_realtime=HINT,
            spinner=False,            # no spinning text in the terminal
            no_log_file=True,         # don't write a log file into the project folder
            # Live caption: a second, tiny model transcribes while you're still talking.
            enable_realtime_transcription=on_live_text is not None,
            realtime_model_type=LIVE_MODEL,
            on_realtime_transcription_update=on_live_text,
        )
        # Only one transcription at a time: push-to-talk and always-listening
        # share the same recorder, so they take turns using Whisper.
        self._whisper_lock = threading.Lock()
        # Set whenever listen_for_phrase() is NOT in its "waiting for a voice"
        # part, so stop_listening() knows when it's safe to carry on.
        self._not_waiting = threading.Event()
        self._not_waiting.set()
        self.last_phrase_started = 0.0   # when the last overheard phrase began (time.time())

    def start(self) -> None:
        """Start recording right now (talk key pressed)."""
        self._recorder.start()

    def stop_and_transcribe(self) -> str:
        """
        Stop recording (talk key released) and return what was said.
        This waits while Whisper works, so call it off the main thread.
        """
        self._recorder.stop()
        with self._whisper_lock:
            return (self._recorder.text() or "").strip()

    # --- Always listening -------------------------------------------------

    def listen_for_phrase(self, stop: threading.Event, until: float | None = None) -> str:
        """
        Wait for someone to speak, record until they pause, and return the text.

        Returns "" straight away if `stop` gets set (Space pressed, a typed
        message, closing...), or if `until` (a time.time() value) passes
        with nobody talking. Blocks, so run it on a background thread.
        """
        recorder = self._recorder
        self._not_waiting.clear()
        try:
            self._throw_away_old_recordings()
            # The library keeps the last second of sound, to add to the start
            # of each recording. Empty it, so it can't hold E.V.E.'s own last words.
            buffer = getattr(recorder, "audio_buffer", None)
            if buffer is not None:
                buffer.clear()
            # Tell the library: start recording when you hear a voice, and
            # stop when it goes quiet. (It records, but doesn't transcribe.)
            recorder.start_recording_on_voice_activity = True
            recorder.stop_recording_on_voice_deactivity = True
            heard = False
            while not stop.is_set():
                if not recorder.recorded_audio_queue.empty():
                    heard = True   # a whole phrase has been recorded
                    break
                if until and time.time() > until and not recorder.is_recording:
                    break          # nobody spoke in time
                time.sleep(0.02)
            self._stop_listening_by_itself()
            if not heard:
                # Stopped early: drop anything half-recorded.
                if recorder.is_recording:
                    recorder.stop()
                self._throw_away_old_recordings()
                return ""
            self.last_phrase_started = recorder.recording_start_time
        finally:
            self._not_waiting.set()
        # Now turn the recorded phrase into text (this part takes a moment).
        with self._whisper_lock:
            return (recorder.text() or "").strip()

    def stop_listening(self, stop: threading.Event) -> None:
        """
        Stop a listen_for_phrase() that's waiting for a voice (call from any
        thread). Waits a moment until it has really let go of the microphone,
        so push-to-talk can start straight after.
        """
        stop.set()
        self._not_waiting.wait(timeout=0.5)

    def _stop_listening_by_itself(self) -> None:
        """
        Switch off voice-activated recording. By default the library keeps
        listening on its own after the first phrase, and would record E.V.E.'s
        own voice while she talks. This turns that off.
        """
        recorder = self._recorder
        recorder.start_recording_on_voice_activity = False
        recorder.stop_recording_on_voice_deactivity = False
        recorder.continuous_listening = False

    def _throw_away_old_recordings(self) -> None:
        """Empty the library's queue of recorded phrases nobody has transcribed."""
        queue_ = self._recorder.recorded_audio_queue
        while not queue_.empty():
            try:
                queue_.get_nowait()
            except Exception:
                break

    def shutdown(self) -> None:
        """Release the microphone and stop RealtimeSTT's helper processes."""
        # RealtimeSTT has a small bug that prints a scary but harmless error
        # while closing. Mute its messages just for the shutdown.
        logging.getLogger("realtimestt").setLevel(logging.CRITICAL)
        self._recorder.shutdown()


if __name__ == "__main__":
    # Self-test: run  .venv\Scripts\python -m voice.stt
    # Press Enter to start talking, Enter again to stop. Type q then Enter to quit.
    # Or:  .venv\Scripts\python -m voice.stt listen   for always-listening mode:
    # just talk, and it prints each phrase it hears. Ctrl+C to stop.
    import sys

    def show_live(text: str) -> None:
        # "\r" jumps back to the start of the line, so each update overwrites
        # the last one. Padding with spaces wipes any longer, older text.
        print(f"\r   ...{text[-70:]:<75}", end="", flush=True)

    print("Loading speech models (the first run downloads them into models\\)...")
    stt = SpeechToText(on_live_text=show_live)
    print("Ready.")
    try:
        if sys.argv[1:] == ["listen"]:
            print("Always listening. Say something, then pause. Ctrl+C to stop.")
            never = threading.Event()
            while True:
                print(f"\nHeard: \"{stt.listen_for_phrase(never)}\"")
        while True:
            if input("\nPress Enter to talk (q to quit): ").strip().lower() == "q":
                break
            print("Recording... press Enter when you've finished.")
            stt.start()
            input()
            print("\nTranscribing...")
            print(f"You said: \"{stt.stop_and_transcribe()}\"")
    finally:
        stt.shutdown()
