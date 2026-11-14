import os
import sys

from dotenv import load_dotenv
from PySide6.QtWidgets import QApplication

from paths import BASE_DIR
from ui.event_log import EventLog
from ui.eye_animator import EyeAnimator
from ui.hud_window import HudWindow
from voice.voice_controller import VoiceController

load_dotenv(BASE_DIR / ".env")


def main():
    app = QApplication(sys.argv)

    key_ok = "yes" if os.getenv("GEMINI_API_KEY") else "NO"
    print(f"E.V.E. starting. Gemini key loaded: {key_ok}")

    # The animator and log are created here, not inside the window, so the
    # voice and brain code can be handed the same objects and drive the HUD.
    animator = EyeAnimator()
    event_log = EventLog()   # anything can add a line: event_log.log("...")
    window = HudWindow(animator, event_log)
    voice = VoiceController()

    # --- Wiring: connect signals from one part to functions in another ---
    # Window -> voice: holding and releasing Space.
    window.talk_pressed.connect(voice.talk_pressed)
    window.talk_released.connect(voice.talk_released)
    # Window -> voice: M switches the brain between fast and think mode.
    window.mode_toggle_pressed.connect(voice.toggle_mode)
    # Voice -> window: log lines, captions and the brain's mode.
    voice.log.connect(lambda message, source: event_log.log(message, source))
    voice.caption.connect(window.show_caption)
    voice.subtitle.connect(window.show_subtitle)   # her sentences, typewriter-style
    voice.mode_changed.connect(window.show_mode)
    # Voice -> eye: listening / thinking / speaking / idle, and the speaking pulse.
    voice.state.connect(animator.set_state)
    voice.level.connect(animator.set_audio_level)
    # Stay in BOOTING after the boot text until the voice says it's ready,
    # so STANDBY really means "ready for you".
    window.boot.wait_for_ready = True
    # Once she's ready, a replayed boot (B key) can go straight back to STANDBY.
    voice.ready.connect(lambda: setattr(window.boot, "wait_for_ready", False))
    # Load the speech models once the boot animation has finished.
    window.boot.finished.connect(voice.start)
    # Free the microphone when the program closes.
    app.aboutToQuit.connect(voice.shutdown)

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    # This "if" matters for voice: RealtimeSTT starts helper processes, and on
    # Windows each one re-reads this file. The check stops them opening a HUD too.
    main()
