"""
The list of moods E.V.E.'s eye can be in.

An Enum is a fixed set of named choices. Using EyeState.LISTENING
instead of a plain string like "listening" means a typo becomes an
error straight away instead of a silent bug.
"""

from enum import Enum


class EyeState(Enum):
    BOOTING = "booting"      # startup: rings twist open
    IDLE = "idle"            # resting: slow breathing glow, gentle rotation
    LISTENING = "listening"  # focus: rings turn opposite ways and push out (dilate)
    THINKING = "thinking"    # working: rings spin faster
    SPEAKING = "speaking"    # talking: eye pulses with the voice volume
    LOOKING = "looking"      # curious: pupil drifts around
    SHUTDOWN = "shutdown"    # closing: rings twist shut and the glow fades out


# Temporary test keys (1-5) used by the HUD window until voice control exists.
STATE_KEYS = {
    "1": EyeState.IDLE,
    "2": EyeState.LISTENING,
    "3": EyeState.THINKING,
    "4": EyeState.SPEAKING,
    "5": EyeState.LOOKING,
}


if __name__ == "__main__":
    # Quick self-test: run  .venv\Scripts\python -m ui.eye_state
    print("E.V.E. eye states:")
    for state in EyeState:
        print(f"  {state.name}")
    print("Test keys:")
    for key, state in STATE_KEYS.items():
        print(f"  {key} -> {state.name}")
