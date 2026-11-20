"""
Try one of E.V.E.'s tools on its own, with no brain, HUD or voice.

    .venv\\Scripts\\python -m actions weather Leeds
    .venv\\Scripts\\python -m actions weather            (uses EVE_HOME_CITY)
    .venv\\Scripts\\python -m actions wiki Ada Lovelace
    .venv\\Scripts\\python -m actions search best pizza in Rome
    .venv\\Scripts\\python -m actions news Formula 1
    .venv\\Scripts\\python -m actions open_app spotify
    .venv\\Scripts\\python -m actions close notepad
    .venv\\Scripts\\python -m actions open_site youtube
    .venv\\Scripts\\python -m actions search_site youtube lo-fi beats
    .venv\\Scripts\\python -m actions timer 5 pasta      (5 seconds; waits for it)
    .venv\\Scripts\\python -m actions volume up          (or: down, 40, "down 20")
    .venv\\Scripts\\python -m actions mute               (or: unmute)
    .venv\\Scripts\\python -m actions media next         (or: play_pause, previous)
    .venv\\Scripts\\python -m actions screen             (takes a picture, shows its size, throws it away)
    .venv\\Scripts\\python -m actions find essay
    .venv\\Scripts\\python -m actions find essay in documents
    .venv\\Scripts\\python -m actions list documents
    .venv\\Scripts\\python -m actions open_file notes.docx
    .venv\\Scripts\\python -m actions board              (example working; prints it, as there's no HUD)

It prints exactly what Gemini will be handed.
"""

import json
import sys
import time

from dotenv import load_dotenv

from paths import BASE_DIR

load_dotenv(BASE_DIR / ".env")

from actions import describe, run_tool  # noqa: E402  (after loading .env on purpose)

SHORTCUTS = {
    "weather": ("get_weather", "place", {}),
    "wiki": ("look_up_wikipedia", "topic", {}),
    "search": ("search_web", "query", {}),
    "news": ("search_web", "query", {"recent_news": True}),
    "open_app": ("open_app", "name", {}),
    "close": ("close_app", "name", {}),
    "open_site": ("open_website", "site", {}),
    "search_site": ("open_website", "site", {}),   # first word = site, the rest = search
    "timer": ("set_timer", "seconds", {}),         # first word = seconds, the rest = label
    "volume": ("change_volume", "action", {}),     # "up", "down", "up 20", or a number to set it
    "mute": ("change_volume", "action", {}),
    "unmute": ("change_volume", "action", {}),
    "media": ("control_media", "action", {}),
    "screen": ("look_at_screen", "question", {}),
    "find": ("find_files", "name", {}),             # "find essay in documents" also works
    "list": ("list_folder", "folder", {}),
    "open_file": ("open_file", "name", {}),
    "board": ("show_working", "subject", {}),
}

if len(sys.argv) < 2 or sys.argv[1] not in SHORTCUTS:
    print(__doc__)
    sys.exit()

name, field, extra = SHORTCUTS[sys.argv[1]]
if sys.argv[1] == "search_site":
    args = {"site": sys.argv[2] if len(sys.argv) > 2 else "", "search": " ".join(sys.argv[3:])}
elif sys.argv[1] == "timer":
    args = {"seconds": int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 0,
            "label": " ".join(sys.argv[3:])}
elif sys.argv[1] in ("mute", "unmute"):
    args = {"action": sys.argv[1]}
elif sys.argv[1] == "volume":
    words = sys.argv[2:] or ["up"]
    if words[0].isdigit():   # "volume 40" = set it to 40
        args = {"action": "set", "level": int(words[0])}
    else:                    # "volume up" or "volume down 20"
        args = {"action": words[0], "level": int(words[1]) if len(words) > 1 and words[1].isdigit() else 0}
elif sys.argv[1] == "board":
    args = {"subject": "Solve 2x + 5 = 17", "maths": ["2x + 5 = 17", "2x = 12", r"x = \frac{12}{2}"],
            "notes": ["the question", "take 5 from both sides"], "answer": "x = 6",
            "say_aloud": "Take five off both sides, then halve it. x is six, sir."}
elif sys.argv[1] in ("find", "open_file") and " in " in " ".join(sys.argv[2:]):
    what, where = " ".join(sys.argv[2:]).rsplit(" in ", 1)
    args = {"name": what, "folder": where}
else:
    args = {field: " ".join(sys.argv[2:]), **extra}
print(describe(name, args))
start = time.time()
result = run_tool(name, args)
if "_image" in result:   # don't print a screenshot as text: just say how big it was
    result["_image"] = f"<JPEG picture, {len(result['_image']) // 1024} KB, kept in memory only>"
print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
print(f"({time.time() - start:.1f}s)")

if name == "set_timer" and "set" in result:
    # Wait for the timer to go off, the way E.V.E. would.
    import threading
    from actions.timers import get_timers
    done = threading.Event()
    get_timers().when_done(lambda timer: (print(f"DONE: {timer.announcement()}"), done.set()))
    while not done.wait(1):
        for timer in get_timers().running():
            print(f"  {timer.seconds_left():.0f}s left ", end="\r")
