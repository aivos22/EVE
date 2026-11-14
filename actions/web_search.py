"""
Web search tool: the top results for a search, like a quick look on Google.

Uses the free `ddgs` package (no key). It can ask several search engines;
"auto" lets it pick whichever is working, because some of them block
programs from time to time.
"""

from ddgs import DDGS

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
    if recent_news:
        hits = search.news(query, max_results=MAX_RESULTS)
    else:
        hits = search.text(query, max_results=MAX_RESULTS, backend="auto")
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
