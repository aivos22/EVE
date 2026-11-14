"""
Chat with E.V.E.'s brain in the terminal, with no HUD and no voice.

    .venv\\Scripts\\python -m brain

Type a message and press Enter. Type "quit" (or press Ctrl+C) to stop.
"""

import time

from dotenv import load_dotenv

from paths import BASE_DIR

load_dotenv(BASE_DIR / ".env")

from brain.gemini_brain import Brain  # noqa: E402  (after loading .env on purpose)

brain = Brain()
print(f"E.V.E. brain test, using {brain.model}. Type 'quit' to stop.\n")

while True:
    try:
        text = input("You  > ").strip()
    except (KeyboardInterrupt, EOFError):
        break
    if text.lower() in ("quit", "exit"):
        break
    if not text:
        continue
    start = time.time()
    reply = brain.respond(text)
    print(f"EVE  > {reply}   ({time.time() - start:.1f}s, remembers {len(brain.history) // 2} exchanges)\n")
