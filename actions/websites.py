"""
The open_website tool: opens a web page in sir's default browser.

Three ways to use it:
    open_website("youtube")                      a site from data/actions.json
    open_website("youtube", search="lo-fi beats") that site's search page
    open_website("https://example.com/page")      a full web address

Only http:// and https:// addresses are ever opened. Other kinds of link
("file:", "javascript:", app links...) are refused, because they can do
much more than show a page. Search words are made "web-safe" (spaces become
+, symbols become codes like %26), so they can't change the address itself.

Test it alone:
    .venv\\Scripts\\python -m actions open_site youtube
    .venv\\Scripts\\python -m actions search_site youtube lo-fi beats
"""

import re
import webbrowser
from urllib.parse import quote_plus, urlsplit

from actions import settings

# A bare web address with no http:// in front, like "bbc.co.uk" or "www.python.org/doc".
BARE_ADDRESS = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+(/\S*)?$", re.IGNORECASE)


def open_website(site: str, search: str = "") -> dict:
    """
    Open a website in sir's web browser, optionally searching it.
    Use it when sir asks to open, go to or show a website, or to search a
    particular site, e.g. "open YouTube" or "search YouTube for lo-fi beats".
    For "search for X" with no site named, use site "google".
    Don't use this to answer questions yourself: use search_web for that.
    Opening an app (Spotify, Discord...) is open_app, not this.

    Args:
        site: A site's name, e.g. "youtube", "bbc news", "amazon", or a full
            web address starting with https://.
        search: What to search for on that site. Leave empty to just open it.
    """
    site = site.strip()
    search = " ".join(search.split())
    # Most results have a "say" line: what she says straight away, without
    # asking Gemini to word it (one request saved; see actions/__init__.py).
    # "Can't search that site" has none, so Gemini can offer another way.
    try:
        friendly, entry = settings.find("websites", site)
    except settings.SettingsError as error:
        return {"error": str(error), "say": "My actions file has a mistake in it, sir. The log has the details."}

    if friendly:
        if search:
            template = entry.get("search")
            if not template:
                return {"error": f"I don't have a search address for {friendly}",
                        "tell_sir": f"Add a \"search\" line for {friendly} in data/actions.json."}
            url = template.replace("{}", quote_plus(search))
        else:
            url = entry["url"]
        name = friendly
    else:
        # Not a site on the list: it must be a web address.
        if BARE_ADDRESS.match(site):
            site = "https://" + site   # "bbc.co.uk" -> "https://bbc.co.uk"
        if search:
            return {"error": f"I can only search sites on the list, and {site} isn't one",
                    "sites_i_can_search": [n for n, e in settings.load()["websites"].items() if e.get("search")]}
        url = site
        name = None

    problem = unsafe(url)
    if problem:
        if friendly is None and not url.lower().startswith(("http://", "https://")) and ":" not in url:
            # Just a name we don't know, rather than a bad address.
            return {"error": f"{site} isn't a website I know",
                    "tell_sir": "Add it to data/actions.json, or give me its full address.",
                    "websites_i_know": settings.known_names("websites"),
                    "say": f"I don't know a website called {site}, sir. "
                           "You can add it to the actions file in my data folder."}
        return {"error": f"I won't open that address: {problem}",
                "say": "I'd rather not open that address, sir. It doesn't look like an ordinary web page."}

    if not webbrowser.open(url):
        return {"error": "Windows couldn't open the web browser",
                "say": "Windows wouldn't open the web browser for me, sir."}
    # For an address, say just the site's name: "python.org", not "https://www.python..."
    name = name or urlsplit(url).hostname.removeprefix("www.")
    result = {"opened": name}
    if search:
        result["searched_for"] = search
        result["say"] = f"Searching {name} for {search}, sir."
    else:
        result["say"] = f"Opening {name}, sir."
    return result


def unsafe(url: str) -> str:
    """Why this address mustn't be opened, or "" if it's fine."""
    if any(ch.isspace() or ord(ch) < 32 for ch in url):
        return "it has spaces or hidden characters in it"
    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https"):
        return "only http and https addresses are allowed"
    if not parts.hostname:
        return "it has no website name in it"
    if "@" in parts.netloc:
        # "https://bank.com@evil.com" really goes to evil.com: a known trick.
        return "it has a login part (@) in it"
    return ""
