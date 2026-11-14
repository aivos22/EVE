"""
Text-to-speech: gives E.V.E. a voice.

Speaking is two steps:
    path, source = tts.prepare("Hello")   # make (or find) the audio file
    tts.play(path, on_level)              # play it, reporting loudness for the eye
speak() does both in one go.

Voices, tried in this order:
  1. ElevenLabs: online, the most natural, costs credits.
     Needs ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID in .env.
  2. Kokoro: offline, free, very good. Runs on this PC from models/kokoro.
  3. pyttsx3: the built-in Windows voice. Robotic, but always there.
If one fails, the next one is used. EVE_TTS in .env picks where to start:
"elevenlabs" (the default), "kokoro", or "pyttsx3".

Short phrases ("Yes, sir", greetings, errors) are saved in data/tts_cache
the first time, so they play instantly afterwards and never use credits twice.
"""

import hashlib
import os
import wave

import numpy as np
import pyttsx3

from paths import DATA_DIR, MODELS_DIR
from voice.audio_player import AudioPlayer

TEMP_DIR = DATA_DIR / "tts_temp"     # freshly made speech, overwritten each time
CACHE_DIR = DATA_DIR / "tts_cache"   # saved phrases, kept between runs
CACHE_MAX_CHARS = 80                 # only cache short phrases; long replies are rarely repeated
TEMP_FILES = 8                       # speech_0..7.wav; more than enough sentences "in flight" at once

# ElevenLabs settings
ELEVEN_MODEL = "eleven_flash_v2_5"   # fast, and costs half the credits of the bigger models
ELEVEN_RATE = 22050                  # samples per second of the audio we ask for

# Kokoro settings
KOKORO_DIR = MODELS_DIR / "kokoro"
KOKORO_VOICE = "af_sarah"   # af_ = American female, bf_ = British female
KOKORO_LANG = "en-us"       # use "en-gb" with a bf_ voice
KOKORO_SPEED = 1.0          # 1.0 = normal; 0.9 is a little slower and calmer

# pyttsx3 settings. Windows voices to try, in order. Hazel is British.
PREFERRED_VOICES = ["Hazel", "Zira"]
SPEAKING_RATE = 180   # words per minute (pyttsx3's default is 200)

ENGINE_ORDER = ["elevenlabs", "kokoro", "pyttsx3"]
ENGINE_NAMES = {"elevenlabs": "ElevenLabs", "kokoro": "Kokoro", "pyttsx3": "Windows voice"}


class TextToSpeech:
    def __init__(self):
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.player = AudioPlayer()
        self.notes: list[str] = []   # why a voice was skipped, for the log
        self._temp_number = 0        # which speech_N.wav to write next

        # Where to start in ENGINE_ORDER.
        wanted = os.getenv("EVE_TTS", "elevenlabs").strip().lower()
        start = ENGINE_ORDER.index(wanted) if wanted in ENGINE_ORDER else 0
        self.engines = ENGINE_ORDER[start:]

        # Set up each voice we might use. If one can't start, drop it.
        self._eleven = None
        self.voice_id = os.getenv("ELEVENLABS_VOICE_ID", "")
        if "elevenlabs" in self.engines:
            api_key = os.getenv("ELEVENLABS_API_KEY", "")
            if api_key and self.voice_id:
                from elevenlabs.client import ElevenLabs
                self._eleven = ElevenLabs(api_key=api_key)
            else:
                self._drop("elevenlabs", "key or voice ID missing from .env")

        self._kokoro = None
        if "kokoro" in self.engines:
            model = KOKORO_DIR / "kokoro-v1.0.onnx"
            voices = KOKORO_DIR / "voices-v1.0.bin"
            if model.exists() and voices.exists():
                from kokoro_onnx import Kokoro
                self._kokoro = Kokoro(str(model), str(voices))
            else:
                self._drop("kokoro", "model files not found in models\\kokoro")

    def describe(self) -> str:
        """One line for the log saying which voice is in charge."""
        return f"Voice: {ENGINE_NAMES[self.engines[0]]}"

    # --- The main controls ----------------------------------------------

    def prepare(self, text: str):
        """
        Get a .wav file of `text` being spoken. Returns (file path, source),
        where source says which voice made it, for the log.
        """
        # Already saved by ANY of our voices? Use that straight away. (Most
        # useful offline: no time wasted trying an online voice first.)
        for engine in self.engines:
            cached = self._cache_path(engine, text)
            if cached and cached.exists():
                return cached, f"{ENGINE_NAMES[engine]}, cached"

        problems = []
        for engine in list(self.engines):
            name = ENGINE_NAMES[engine]
            cached = self._cache_path(engine, text)
            if cached and cached.exists():
                return cached, f"{name}, cached"
            path = cached or self._next_temp_file()
            try:
                self._make(engine, text, path)
            except Exception as error:
                problems.append(f"{name} failed: {self._short(error)}")
                self._handle_error(engine, error)
                continue   # try the next voice
            source = name if not problems else f"{name}; {problems[-1]}"
            return path, source
        raise RuntimeError("no voice could speak: " + "; ".join(problems))

    def _next_temp_file(self):
        """
        A fresh file name for new speech: speech_0.wav, speech_1.wav ... then
        round again. When she speaks sentence by sentence, the next sentence
        is being made while this one plays, so they can't share one file.
        """
        self._temp_number = (self._temp_number + 1) % TEMP_FILES
        return TEMP_DIR / f"speech_{self._temp_number}.wav"

    def play(self, wav_path, on_level=None) -> None:
        """Play a prepared file. Waits until she has finished speaking."""
        self.player.play(wav_path, on_level)

    def speak(self, text: str, on_level=None) -> str:
        """Prepare and play in one go. Returns which voice was used."""
        path, source = self.prepare(text)
        self.play(path, on_level)
        return source

    def stop(self) -> None:
        """Stop talking straight away."""
        self.player.stop()

    # --- Choosing and managing voices -----------------------------------

    def _make(self, engine: str, text: str, path) -> None:
        if engine == "elevenlabs":
            self._elevenlabs_to_wav(text, path)
        elif engine == "kokoro":
            self._kokoro_to_wav(text, path)
        else:
            self._pyttsx3_to_wav(text, path)

    def _drop(self, engine: str, reason: str) -> None:
        """Stop using a voice for the rest of this session."""
        if engine in self.engines and len(self.engines) > 1:
            self.engines.remove(engine)
            self.notes.append(f"{ENGINE_NAMES[engine]} off: {reason}")

    def _handle_error(self, engine: str, error: Exception) -> None:
        """
        If ElevenLabs says the key is wrong, a paid plan is needed, or we're
        out of credits, stop asking it this session. Other errors (like a
        network blip) only skip it for this one sentence.
        """
        if engine != "elevenlabs":
            return
        status = getattr(error, "status_code", None)   # the HTTP error number, if any
        message = self._short(error).lower()
        dead_ends = ("quota", "credit", "subscription", "upgrade")   # e.g. "free users cannot use library voices"
        if status in (401, 402) or any(word in message for word in dead_ends):
            self._drop("elevenlabs", self._short(error))

    @staticmethod
    def _short(error: Exception) -> str:
        """A short, readable reason from an error, for the log feed."""
        body = getattr(error, "body", None)   # ElevenLabs puts its explanation here
        if isinstance(body, dict) and isinstance(body.get("detail"), dict):
            return str(body["detail"].get("message", ""))[:90]
        text = str(error).strip()
        return text.splitlines()[0][:90] if text else type(error).__name__

    # --- Phrase cache ---------------------------------------------------

    def _cache_path(self, engine: str, text: str):
        """
        Where a short phrase would be saved, or None if we don't cache it.
        The file name is a "hash" of the voice and the words: a short code
        that is always the same for the same input, so we can find it again.
        """
        key_text = " ".join(text.lower().split())   # ignore case and extra spaces
        if engine == "pyttsx3" or len(key_text) > CACHE_MAX_CHARS:
            return None   # the Windows voice is instant anyway
        voice = f"{self.voice_id}|{ELEVEN_MODEL}" if engine == "elevenlabs" else f"{KOKORO_VOICE}|{KOKORO_SPEED}"
        key = hashlib.sha1(f"{engine}|{voice}|{key_text}".encode()).hexdigest()[:16]
        return CACHE_DIR / f"{engine}_{key}.wav"

    @staticmethod
    def _save_wav(samples_16bit: bytes, rate: int, wav_path) -> None:
        """
        Write audio to a .wav file. We write to a temporary file first, then
        swap it into place, so a failure halfway never leaves a broken file
        in the cache.
        """
        # Each file gets its own temporary name, because an interrupted reply can
        # still be finishing a sentence while the next reply starts making one.
        temp = TEMP_DIR / f"writing_{wav_path.name}"
        with wave.open(str(temp), "wb") as wav:
            wav.setnchannels(1)    # mono
            wav.setsampwidth(2)    # 16-bit samples
            wav.setframerate(rate)
            wav.writeframes(samples_16bit)
        os.replace(temp, wav_path)

    # --- ElevenLabs -----------------------------------------------------

    def _elevenlabs_to_wav(self, text: str, wav_path) -> None:
        # We ask for raw "PCM" audio (plain numbers, no compression), which
        # arrives in pieces, then wrap it in a .wav file ourselves.
        pieces = self._eleven.text_to_speech.convert(
            voice_id=self.voice_id,
            text=text,
            model_id=ELEVEN_MODEL,
            output_format=f"pcm_{ELEVEN_RATE}",
        )
        self._save_wav(b"".join(pieces), ELEVEN_RATE, wav_path)

    # --- Kokoro (offline, on this PC) -----------------------------------

    def _kokoro_to_wav(self, text: str, wav_path) -> None:
        # Kokoro gives back the sound as decimals between -1 and 1. A .wav
        # file wants whole numbers between -32767 and 32767, so we scale them.
        samples, rate = self._kokoro.create(text, voice=KOKORO_VOICE, speed=KOKORO_SPEED, lang=KOKORO_LANG)
        pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
        self._save_wav(pcm.tobytes(), rate, wav_path)

    # --- pyttsx3 (the built-in Windows voice) ---------------------------

    @staticmethod
    def _pyttsx3_to_wav(text: str, wav_path) -> None:
        # We make a fresh engine each time. pyttsx3 gets confused if one
        # engine is reused from different threads, and the app calls this
        # from a background thread.
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
    # She says two sentences; a bar shows the loudness the eye will use.
    # Run it twice: the second time the short phrase comes from the cache.
    from dotenv import load_dotenv
    from paths import BASE_DIR

    load_dotenv(BASE_DIR / ".env")
    tts = TextToSpeech()
    print(tts.describe())
    for note in tts.notes:
        print(f"  ({note})")

    def show_level(level: float) -> None:
        bar = "#" * int(level * 40)
        print(f"\r  loudness |{bar:<40}|", end="", flush=True)

    for sentence in ["Hello. I am Eve.", "All systems are online, and I am ready when you are."]:
        path, source = tts.prepare(sentence)
        print(f"\nSaying ({source}): {sentence}")
        tts.play(path, on_level=show_level)
    print("\nDone.")
