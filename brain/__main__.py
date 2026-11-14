"""
Chat with E.V.E.'s brain in the terminal, with no HUD and no voice.

    .venv\\Scripts\\python -m brain

Type a message and press Enter. Each sentence is printed the moment it's
ready, with how long it took, so you can see streaming at work.
Type "mode" to switch fast/think, and "quit" (or press Ctrl+C) to stop.
"""

import time

from dotenv import load_dotenv

from paths import BASE_DIR

load_dotenv(BASE_DIR / ".env")

from brain.gemini_brain import Brain  # noqa: E402  (after loading .env on purpose)

brain = Brain()
brain.on_note = lambda note: print(f"       ({note})")
print(f"E.V.E. brain test: {brain.describe()}. Type 'mode' to switch, 'quit' to stop.\n")

while True:
    try:
        text = input("You  > ").strip()
    except (KeyboardInterrupt, EOFError):
        break
    if text.lower() in ("quit", "exit"):
        break
    if text.lower() == "mode":
        brain.toggle_mode()
        print(f"       Now in {brain.describe()}\n")
        continue
    if not text:
        continue
    start = time.time()
    for number, sentence in enumerate(brain.respond_stream(text), 1):
        prefix = "EVE  >" if number == 1 else "      "
        print(f"{prefix} [{time.time() - start:4.1f}s] {sentence}")
    print(f"       (remembers {len(brain.history) // 2} exchanges)\n")
