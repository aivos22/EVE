"""
Try one of E.V.E.'s tools on its own, with no brain, HUD or voice.

    .venv\\Scripts\\python -m actions weather Leeds
    .venv\\Scripts\\python -m actions weather            (uses EVE_HOME_CITY)
    .venv\\Scripts\\python -m actions wiki Ada Lovelace
    .venv\\Scripts\\python -m actions search best pizza in Rome
    .venv\\Scripts\\python -m actions news Formula 1
    .venv\\Scripts\\python -m actions open_app spotify
    .venv\\Scripts\\python -m actions open_site youtube
    .venv\\Scripts\\python -m actions search_site youtube lo-fi beats

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
    "open_site": ("open_website", "site", {}),
    "search_site": ("open_website", "site", {}),   # first word = site, the rest = search
}

if len(sys.argv) < 2 or sys.argv[1] not in SHORTCUTS:
    print(__doc__)
    sys.exit()

name, field, extra = SHORTCUTS[sys.argv[1]]
if sys.argv[1] == "search_site":
    args = {"site": sys.argv[2] if len(sys.argv) > 2 else "", "search": " ".join(sys.argv[3:])}
else:
    args = {field: " ".join(sys.argv[2:]), **extra}
print(describe(name, args))
start = time.time()
result = run_tool(name, args)
print(json.dumps(result, indent=2, ensure_ascii=False))
print(f"({time.time() - start:.1f}s)")
