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

from dotenv import load_dotenv

from paths import BASE_DIR, MODELS_DIR

# Read .env now, because the settings below are read the moment this file is
# imported (main.py loads .env too, but only after importing us). Settings
# already set aren't overwritten, so loading it twice is harmless.
load_dotenv(BASE_DIR / ".env")
# Tell the libraries RealtimeSTT uses where to keep their downloads.
# This MUST happen before RealtimeSTT is imported, so it's at the top.
WHISPER_DIR = MODELS_DIR / "whisper"
os.environ.setdefault("HF_HOME", str(MODELS_DIR / "huggingface"))
os.environ.setdefault("TORCH_HOME", str(MODELS_DIR / "torch"))

import numpy as np  # noqa: E402
import torch  # noqa: E402  (imported after the settings above on purpose)
from RealtimeSTT import AudioToTextRecorder  # noqa: E402

FINAL_MODEL = "base.en"  # accurate model for the final transcript
LIVE_MODEL = "tiny.en"   # small, fast model for the live caption while you talk

SAMPLE_RATE = 16000      # the library records 16,000 sound samples a second


def _setting(name: str, default: float) -> float:
    """A number from .env, or the default if it's missing or not a number."""
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


# How easily the voice detector decides "someone is talking" (0 to 1).
# Higher = catches quieter voices (and more far-away chatter); lower = you
# have to speak up a bit. The library's own default is 0.4.
VOICE_SENSITIVITY = _setting("EVE_VOICE_SENSITIVITY", 0.25)

# Hands-free listening ignores any phrase quieter than this (0 to 1), so
# people talking across the room don't count. Someone near the mic is far
# louder than someone a few metres away. Tune it with the self-test at the
# bottom of this file: it prints the level of everything it hears.
# 0 switches the check off. Push-to-talk (Space) is never checked.
MIN_VOICE_LEVEL = _setting("EVE_MIN_VOICE_LEVEL", 0.015)


def voice_level(audio) -> float:
    """
    How loud a recorded phrase was, from 0 (silent) to 1 (as loud as possible).

    The recording is chopped into 30 ms slices and each slice's loudness is
    measured (RMS: the "average size" of the sound wave). A phrase also has
    pauses and quiet bits, so we don't average everything: we take a slice
    near the top (90th percentile), which is roughly "how loud the speech was".
    """
    if audio is None or len(audio) == 0:
        return 0.0
    audio = np.asarray(audio, dtype=np.float32)
    size = int(SAMPLE_RATE * 0.03)
    usable = len(audio) // size * size
    if usable == 0:
        return float(np.sqrt(np.mean(audio ** 2)))
    slices = audio[:usable].reshape(-1, size)
    loudness = np.sqrt(np.mean(slices ** 2, axis=1))
    return float(np.percentile(loudness, 90))

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
            silero_sensitivity=VOICE_SENSITIVITY,
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
        self.last_phrase_level = 0.0     # how loud it was (see voice_level)

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
        with self._whisper_lock:
            # Fetch the recorded sound and check how loud it was BEFORE
            # turning it into text, so far-away voices are dropped cheaply.
            recorder.wait_audio()
            if recorder.is_shut_down:
                return ""
            level = voice_level(recorder.audio)
            self.last_phrase_level = level
            if level < MIN_VOICE_LEVEL:
                logging.getLogger("eve").debug(
                    f"Ignored a quiet voice (level {level:.3f}, needs {MIN_VOICE_LEVEL:.3f})")
                return ""
            # Loud enough: turn it into text (this part takes a moment).
            return (recorder.transcribe() or "").strip()

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

    def set_microphone(self, on: bool) -> None:
        """
        Muting: with on=False the library throws away everything the microphone
        hears, so nothing can be recorded or turned into text. (The microphone
        stays connected, so unmuting is instant.)
        """
        try:
            self._recorder.set_microphone(on)
        except Exception:
            # Older/newer library without this switch: the voice controller's
            # own mute (no listening, no push-to-talk) still applies.
            logging.getLogger("eve").warning("Speech library has no microphone switch", exc_info=True)

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
            print(f"Phrases quieter than {MIN_VOICE_LEVEL:.3f} are ignored "
                  f"(EVE_MIN_VOICE_LEVEL in .env). Voice sensitivity: {VOICE_SENSITIVITY}.")
            never = threading.Event()
            while True:
                heard = stt.listen_for_phrase(never)
                level = stt.last_phrase_level
                if level < MIN_VOICE_LEVEL:
                    print(f"\nlevel {level:.3f}  IGNORED (too quiet)")
                else:
                    print(f"\nlevel {level:.3f}  Heard: \"{heard}\"")
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
