"""
Volume and media controls: "turn it up", "volume 40", "mute", "pause",
"next song", "previous track".

Two tools (not seven), because every tool's description is sent to Gemini
with EVERY request, so fewer tools keeps every request smaller:

    change_volume(action, level)   up / down / set / mute / unmute
    control_media(action)          play_pause / next / previous

Volume uses pycaw, a small library that talks to Windows' own volume
control (the same one as the speaker icon on the taskbar), so she can set
an exact level and know whether sound is muted.

Media presses the same "media keys" some keyboards have. Windows sends
them to whatever is playing: Spotify, YouTube in a browser, VLC...
She can't tell whether that was play or pause, so she just says "Done".

Nothing here is risky or hard to undo, so none of it asks first.
Every result has a "say" line, so each command costs one Gemini request.

Test it alone:
    .venv\\Scripts\\python -m actions volume up
    .venv\\Scripts\\python -m actions volume 40
    .venv\\Scripts\\python -m actions mute
    .venv\\Scripts\\python -m actions media next
"""

import ctypes
import logging
from contextlib import contextmanager

diary = logging.getLogger("eve")

STEP = 10   # how far "up" / "down" moves the volume, in percent, if sir doesn't say

# The media keys' code numbers in Windows ("virtual key codes").
MEDIA_KEYS = {
    "play_pause": (0xB3, "Done, sir."),
    "next": (0xB0, "Skipping, sir."),
    "previous": (0xB1, "Going back, sir."),
}
# Other words Gemini might use for the same thing.
MEDIA_ALIASES = {"play": "play_pause", "pause": "play_pause", "resume": "play_pause", "stop": "play_pause",
                 "skip": "next", "next_track": "next", "back": "previous", "prev": "previous",
                 "previous_track": "previous", "last": "previous"}
VOLUME_ALIASES = {"louder": "up", "increase": "up", "raise": "up", "quieter": "down",
                  "decrease": "down", "lower": "down", "to": "set", "level": "set"}

KEY_EXTENDED = 0x0001   # media keys count as "extended" keys
KEY_UP = 0x0002


@contextmanager
def _speakers():
    """
    Windows' volume control for the default speakers.

    Windows' sound system uses "COM", and COM must be switched on for each
    thread that uses it. Her tools run on the brain's background thread, so
    we switch it on here, use it, and switch it off again.
    """
    import comtypes
    from pycaw.pycaw import AudioUtilities
    comtypes.CoInitialize()
    try:
        yield AudioUtilities.GetSpeakers().EndpointVolume
    finally:
        comtypes.CoUninitialize()


def _percent(volume) -> int:
    return round(volume.GetMasterVolumeLevelScalar() * 100)   # Windows uses 0.0 to 1.0


def change_volume(action: str, level: int = 0) -> dict:
    """
    Change the PC's sound volume. Use it when sir asks to turn the volume or
    sound up or down, set it to a level, or mute / unmute it.

    Args:
        action: "up", "down", "set", "mute" or "unmute".
        level: For "set": the level from 0 to 100 (e.g. "volume 40" is 40,
            "half volume" is 50). For "up" / "down": how much to change it by,
            only if sir said (e.g. "up by 20"); otherwise leave it 0.
    """
    action = VOLUME_ALIASES.get(str(action).strip().lower(), str(action).strip().lower())
    try:
        level = int(round(float(level or 0)))
    except (TypeError, ValueError):
        level = 0
    if action not in ("up", "down", "set", "mute", "unmute"):
        return {"error": f"unknown volume action {action}", "say": "I'm not sure what to do with the volume, sir."}
    if action == "set" and not 0 <= level <= 100:
        return {"error": f"level {level} is outside 0-100", "say": "The volume goes from 0 to 100, sir."}
    try:
        with _speakers() as volume:
            if action == "mute":
                volume.SetMute(1, None)
                return {"muted": True, "say": "Muted, sir."}
            if action == "unmute":
                volume.SetMute(0, None)
                return {"muted": False, "volume": _percent(volume), "say": "Sound back on, sir."}
            if action == "set":
                new = level
            else:
                step = abs(level) or STEP
                new = _percent(volume) + (step if action == "up" else -step)
            new = max(0, min(100, new))
            volume.SetMasterVolumeLevelScalar(new / 100, None)
            if new > 0:
                volume.SetMute(0, None)   # like the taskbar: changing the volume unmutes
            return {"volume": new, "say": f"Volume at {new} percent, sir."}
    except Exception as error:   # no speakers plugged in, sound service stopped...
        diary.warning(f"Volume change ({action} {level}) failed: {error!r}")
        return {"error": f"couldn't reach Windows' volume control: {error}"[:200],
                "say": "I couldn't reach the volume control, sir. Are your speakers plugged in?"}


def control_media(action: str) -> dict:
    """
    Play, pause or skip whatever is playing on sir's PC: Spotify, YouTube,
    or any other music or video. Use it when sir says play, pause, resume,
    next song, skip, previous track, go back and so on.

    Args:
        action: "play_pause" (for play, pause, resume or stop), "next" or "previous".
    """
    action = str(action).strip().lower().replace(" ", "_").replace("/", "_")
    action = MEDIA_ALIASES.get(action, action)
    if action not in MEDIA_KEYS:
        return {"error": f"unknown media action {action}", "say": "I'm not sure what to do with the music, sir."}
    key, said = MEDIA_KEYS[action]
    try:
        # Press and let go of the key, exactly like a keyboard would.
        ctypes.windll.user32.keybd_event(key, 0, KEY_EXTENDED, 0)
        ctypes.windll.user32.keybd_event(key, 0, KEY_EXTENDED | KEY_UP, 0)
    except OSError as error:
        diary.warning(f"Media key {action} failed: {error!r}")
        return {"error": f"couldn't press the media key: {error}", "say": "Windows wouldn't take the media key, sir."}
    return {"pressed": action, "say": said}
