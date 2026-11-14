"""
Microphone check: is there a microphone, and can we actually use it?

    problem = check_microphone()
    if problem:
        print("Can't hear you:", problem)    # e.g. "no microphone found"

It tries to listen for a tenth of a second. That catches the three usual
problems: nothing plugged in, another app holding the mic, or Windows
privacy settings blocking it. It returns None if all is well.
"""

import pyaudio

RATE = 16000        # samples per second (what Whisper uses)
TEST_FRAMES = 1600  # a tenth of a second of sound


def check_microphone() -> str | None:
    """Returns None if the microphone works, or a short plain reason if not."""
    audio = pyaudio.PyAudio()
    try:
        # Is there any input device at all?
        inputs = [i for i in range(audio.get_device_count())
                  if audio.get_device_info_by_index(i).get("maxInputChannels", 0) > 0]
        if not inputs:
            return "no microphone found"
        try:
            device = audio.get_default_input_device_info()
        except OSError:
            return "no default microphone set in Windows sound settings"

        # Try to actually listen for a moment.
        try:
            stream = audio.open(format=pyaudio.paInt16, channels=1, rate=RATE,
                                input=True, frames_per_buffer=TEST_FRAMES)
            stream.read(TEST_FRAMES, exception_on_overflow=False)
            stream.close()
        except OSError as error:
            return (f"couldn't open the microphone ({device.get('name', 'unknown')}): "
                    f"it may be in use by another app or blocked in Windows privacy settings "
                    f"[{error}]")
        return None
    finally:
        audio.terminate()   # always let go of the sound system


if __name__ == "__main__":
    # Quick check:  .venv\Scripts\python -m voice.microphone
    problem = check_microphone()
    print("Microphone OK" if problem is None else f"Microphone problem: {problem}")
