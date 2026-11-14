"""
Text-to-speech: gives E.V.E. a voice.

speak("Hello") turns the text into a .wav file, then plays it through
the AudioPlayer, which reports the loudness for the eye's pulse.

For now this uses pyttsx3, which talks through the voices built into
Windows: free, offline, a bit robotic. ElevenLabs (the real voice),
the phrase cache and the automatic fallback are added in step 5.
"""

import pyttsx3

from paths import DATA_DIR
from voice.audio_player import AudioPlayer

TEMP_DIR = DATA_DIR / "tts_temp"   # where freshly made speech is written before playing

# Windows voices to try, in order. Hazel is British, which suits E.V.E.
PREFERRED_VOICES = ["Hazel", "Zira"]
SPEAKING_RATE = 180   # words per minute (pyttsx3's default is 200)


class TextToSpeech:
    def __init__(self):
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        self.player = AudioPlayer()

    def speak(self, text: str, on_level=None) -> None:
        """Say `text` out loud. Waits until she has finished speaking."""
        wav_path = TEMP_DIR / "speech.wav"
        self._pyttsx3_to_wav(text, wav_path)
        self.player.play(wav_path, on_level)

    def stop(self) -> None:
        """Stop talking straight away."""
        self.player.stop()

    # --- pyttsx3 (the offline Windows voice) -----------------------------

    @staticmethod
    def _pyttsx3_to_wav(text: str, wav_path) -> None:
        # We make a fresh engine each time. pyttsx3 gets confused if one
        # engine is reused from different threads, and the app will call
        # this from a background thread.
        engine = pyttsx3.init()
        engine.setProperty("rate", SPEAKING_RATE)
        for voice in engine.getProperty("voices"):
            if any(name in voice.name for name in PREFERRED_VOICES):
                engine.setProperty("voice", voice.id)
                break
        # Save to a file instead of speaking directly, so our own player
        # can play it and measure the loudness as it goes.
        engine.save_to_file(text, str(wav_path))
        engine.runAndWait()
        engine.stop()


if __name__ == "__main__":
    # Self-test: run  .venv\Scripts\python -m voice.tts
    # She says a sentence and a little bar shows the loudness the eye will use.
    tts = TextToSpeech()

    def show_level(level: float) -> None:
        bar = "#" * int(level * 40)
        print(f"\r  loudness |{bar:<40}|", end="", flush=True)

    for sentence in ["Hello. I am Eve.", "All systems are online, and I am ready when you are."]:
        print(f"\nSaying: {sentence}")
        tts.speak(sentence, on_level=show_level)
    print("\nDone.")
