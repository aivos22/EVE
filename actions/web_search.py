"""
Web search tool: the top results for a search, like a quick look on Google.

Uses the free `ddgs` package (no key). It can ask several search engines;
"auto" lets it pick whichever is working, because some of them block
programs from time to time.
"""

from ddgs import DDGS
from ddgs.exceptions import DDGSException

MAX_RESULTS = 5
TIMEOUT = 8   # seconds
SNIPPET_CHARS = 300   # each result's text is cut to this, so Gemini isn't swamped


def search_web(query: str, recent_news: bool = False) -> dict:
    """
    Search the web. Use this for anything current or changing: news, sports
    results, prices, opening times, releases, or anything you're not sure of.

    Args:
        query: What to search for, written like a search-engine query.
        recent_news: True to search recent news articles instead of the whole web.
    """
    search = DDGS(timeout=TIMEOUT)
    # Search engines sometimes turn programs away for a moment, so we have a
    # few ways to ask, and try them in order until one gives results.
    attempts = [lambda: search.news(query, max_results=MAX_RESULTS)] if recent_news else []
    attempts += [
        lambda: search.text(query, max_results=MAX_RESULTS, backend="auto"),
        lambda: search.text(query, max_results=MAX_RESULTS, backend="google"),
        lambda: search.news(query, max_results=MAX_RESULTS),
    ]
    hits, last_error = [], None
    for attempt in attempts:
        try:
            hits = attempt()
        except DDGSException as error:   # "No results found", blocked, etc.
            last_error = error
            continue
        if hits:
            break
    if not hits and last_error:
        raise last_error   # every way failed; run_tool turns this into an error note
    results = []
    for hit in hits:
        result = {"title": hit.get("title", ""), "snippet": hit.get("body", "")[:SNIPPET_CHARS]}
        if hit.get("source"):
            result["source"] = hit["source"]   # e.g. "BBC" (news only)
        if hit.get("date"):
            result["date"] = hit["date"]       # when it was published (news only)
        results.append(result)
    if not results:
        return {"error": f"No results for {query}"}
    return {"query": query, "results": results}
