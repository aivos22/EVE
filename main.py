import os
import sys

from dotenv import load_dotenv
from PySide6.QtWidgets import QApplication

from paths import BASE_DIR
from ui.eye_animator import EyeAnimator
from ui.hud_window import HudWindow

load_dotenv(BASE_DIR / ".env")


def main():
    app = QApplication(sys.argv)

    key_ok = "yes" if os.getenv("GEMINI_API_KEY") else "NO"
    print(f"E.V.E. starting. Gemini key loaded: {key_ok}")

    # The animator is created here, not inside the window, so that later
    # the voice and brain code can be handed the same animator and drive
    # the eye's state (e.g. animator.set_state(EyeState.LISTENING)).
    animator = EyeAnimator()
    window = HudWindow(animator)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
