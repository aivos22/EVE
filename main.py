import os
import sys

from dotenv import load_dotenv
from PySide6.QtWidgets import QApplication

from actions.timers import get_timers
from log_file import log_line, start_log_file
from paths import BASE_DIR
from ui.event_log import EventLog
from ui.eye_animator import EyeAnimator
from ui.hud_window import HudWindow
from voice.voice_controller import VoiceController

load_dotenv(BASE_DIR / ".env")


def main():
    app = QApplication(sys.argv)
    diary = start_log_file()   # data/logs/eve_<today>.txt

    key_ok = "yes" if os.getenv("GEMINI_API_KEY") else "NO"
    print(f"E.V.E. starting. Gemini key loaded: {key_ok}. Diary: {diary}")
    log_line(f"Gemini key loaded: {key_ok}")

    # The animator and log are created here, not inside the window, so the
    # voice and brain code can be handed the same objects and drive the HUD.
    animator = EyeAnimator()
    event_log = EventLog()   # anything can add a line: event_log.log("...")
    # The timers run in actions/timers.py. The window shows them (TIMERS panel)
    # and the voice announces them, so both are handed the same keeper.
    timers = get_timers()
    window = HudWindow(animator, event_log, timers)
    voice = VoiceController(timers)

    # --- Wiring: connect signals from one part to functions in another ---
    # Window -> voice: holding and releasing Space.
    window.talk_pressed.connect(voice.talk_pressed)
    window.talk_released.connect(voice.talk_released)
    # Window -> voice: M switches the brain between fast and think mode.
    window.mode_toggle_pressed.connect(voice.toggle_mode)
    # Window -> voice: W switches the wake word ("Eve") on and off.
    window.wake_toggle_pressed.connect(voice.toggle_wake)
    # Window -> voice: a message typed in the command bar (/ key).
    window.text_submitted.connect(voice.typed)
    # Voice -> window: log lines, captions and the brain's mode.
    voice.log.connect(lambda message, source: event_log.log(message, source))
    voice.log.connect(log_line)   # ...and every log line also goes in the diary file
    voice.caption.connect(window.show_caption)
    voice.subtitle.connect(window.show_subtitle)   # her sentences, typewriter-style
    voice.mode_changed.connect(window.show_mode)
    voice.wake_changed.connect(window.show_wake)
    # Voice -> window: "Eve, shut down" plays the same shutdown as Esc.
    voice.shutdown_requested.connect(window.shutdown)
    # Voice -> eye: listening / thinking / speaking / idle, and the speaking pulse.
    voice.state.connect(animator.set_state)
    voice.level.connect(animator.set_audio_level)
    # Voice -> eye: a timer went off, so flash to get sir's attention.
    voice.timer_done.connect(lambda name: animator.flash())
    # Stay in BOOTING after the boot text until the voice says it's ready,
    # so STANDBY really means "ready for you".
    window.boot.wait_for_ready = True
    # Once she's ready, a replayed boot (B key) can go straight back to STANDBY.
    voice.ready.connect(lambda: setattr(window.boot, "wait_for_ready", False))
    # Load the speech models once the boot animation has finished.
    window.boot.finished.connect(voice.start)
    # Free the microphone when the program closes.
    app.aboutToQuit.connect(voice.shutdown)
    app.aboutToQuit.connect(lambda: log_line("=== E.V.E. closed ==="))

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    # This "if" matters for voice: RealtimeSTT starts helper processes, and on
    # Windows each one re-reads this file. The check stops them opening a HUD too.
    main()
