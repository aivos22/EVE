"""
Wikipedia tool: a short summary of a person, place, thing or event.

Uses Wikipedia's free public API (no key). Two requests:
  1. search for the best-matching article title
  2. get that article's summary (its opening paragraph)
"""

import httpx

# (Wikipedia's older search address, /w/api.php, turns programs away, so we use the newer one.)
SEARCH_URL = "https://en.wikipedia.org/w/rest.php/v1/search/page"
SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/"
TIMEOUT = 8   # seconds
# Wikipedia asks every program to say what it is. (A generic name, nothing personal.)
HEADERS = {"User-Agent": "EVE-desktop-assistant/0.1 (personal hobby project)"}
MAX_CHARS = 1500   # summaries can be long; she only needs the gist


def look_up_wikipedia(topic: str) -> dict:
    """
    Get a short Wikipedia summary of a person, place, thing or historical event.
    Best for facts that don't change often. For news or anything recent, use search_web.

    Args:
        topic: What to look up, e.g. "Ada Lovelace" or "Great Barrier Reef".
    """
    search = httpx.get(SEARCH_URL, headers=HEADERS, timeout=TIMEOUT,
                       params={"q": topic, "limit": 1})
    search.raise_for_status()
    hits = search.json().get("pages") or []
    if not hits:
        return {"error": f"No Wikipedia article found for {topic}"}

    title = hits[0]["title"]
    # "key" is the title as it appears in the web address, e.g. "Ada_Lovelace".
    summary = httpx.get(SUMMARY_URL + hits[0]["key"], headers=HEADERS,
                        timeout=TIMEOUT, follow_redirects=True)
    summary.raise_for_status()
    data = summary.json()
    return {
        "article": data.get("title", title),
        "description": data.get("description", ""),
        "summary": data.get("extract", "")[:MAX_CHARS],
    }
