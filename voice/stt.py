"""
Speech-to-text: turns your voice into text with Whisper (via RealtimeSTT).

Push-to-talk style: call start() when the talk key goes down and
stop_and_transcribe() when it comes up. While you're talking, an optional
`on_live_text` function gets called with a rough "so far" transcript,
for the live caption.

All models are downloaded into MODELS_DIR (not your user cache), so
E.V.E. can be copied to a memory stick with everything she needs.
"""

import logging
import os

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

    def start(self) -> None:
        """Start recording right now (talk key pressed)."""
        self._recorder.start()

    def stop_and_transcribe(self) -> str:
        """
        Stop recording (talk key released) and return what was said.
        This waits while Whisper works, so call it off the main thread.
        """
        self._recorder.stop()
        return (self._recorder.text() or "").strip()

    def shutdown(self) -> None:
        """Release the microphone and stop RealtimeSTT's helper processes."""
        # RealtimeSTT has a small bug that prints a scary but harmless error
        # while closing. Mute its messages just for the shutdown.
        logging.getLogger("realtimestt").setLevel(logging.CRITICAL)
        self._recorder.shutdown()


if __name__ == "__main__":
    # Self-test: run  .venv\Scripts\python -m voice.stt
    # Press Enter to start talking, Enter again to stop. Type q then Enter to quit.
    def show_live(text: str) -> None:
        # "\r" jumps back to the start of the line, so each update overwrites
        # the last one. Padding with spaces wipes any longer, older text.
        print(f"\r   ...{text[-70:]:<75}", end="", flush=True)

    print("Loading speech models (the first run downloads them into models\\)...")
    stt = SpeechToText(on_live_text=show_live)
    print("Ready.")
    try:
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
