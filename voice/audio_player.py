"""
Plays a .wav file and reports how loud it is as it goes.

The audio is played in small chunks (about 1/40th of a second each).
For every chunk we work out its loudness, from 0 (silent) to 1 (very
loud), and pass that to `on_level`. That's what will make the eye
pulse in time with E.V.E.'s voice.
"""

import threading
import wave

import numpy as np
import pyaudio

CHUNK_FRAMES = 512   # samples per chunk; smaller = smoother pulse, more work
LOUDNESS_GAIN = 4.0  # speech is quieter than you'd think, so scale it up a bit


class AudioPlayer:
    def __init__(self):
        self._pa = pyaudio.PyAudio()
        self._stop = threading.Event()

    def play(self, wav_path, on_level=None) -> None:
        """
        Play a .wav file from start to finish (or until stop() is called).
        This waits until playback ends, so call it off the main thread in the app.
        """
        self._stop.clear()
        with wave.open(str(wav_path), "rb") as wav:
            stream = self._pa.open(
                format=self._pa.get_format_from_width(wav.getsampwidth()),
                channels=wav.getnchannels(),
                rate=wav.getframerate(),
                output=True,
            )
            try:
                data = wav.readframes(CHUNK_FRAMES)
                while data and not self._stop.is_set():
                    stream.write(data)   # send this chunk to the speakers
                    if on_level:
                        on_level(self._loudness(data, wav.getsampwidth()))
                    data = wav.readframes(CHUNK_FRAMES)
            finally:
                stream.stop_stream()
                stream.close()
                if on_level:
                    on_level(0.0)   # finished: back to silent

    def stop(self) -> None:
        """Cut playback short (e.g. if you start talking over her)."""
        self._stop.set()

    def close(self) -> None:
        self._pa.terminate()

    @staticmethod
    def _loudness(data: bytes, sample_width: int) -> float:
        """
        RMS ("root mean square") is the usual way to measure loudness:
        square every sample, take the average, then the square root.
        """
        if sample_width != 2:
            return 0.0   # we only make 16-bit audio, so skip anything else
        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        if samples.size == 0:
            return 0.0
        rms = float(np.sqrt(np.mean(samples ** 2)))
        return min(1.0, rms * LOUDNESS_GAIN)
