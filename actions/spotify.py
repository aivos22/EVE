"""
Spotify: play a song, artist, album or playlist sir names, queue a song,
and say what's playing.

This uses Spotify's official way for apps to control it (the "Web API"),
through the spotipy library. It needs Spotify Premium: Spotify only lets
apps start a particular song on Premium accounts.

How it fits together:
    E.V.E.  --"search: blinding lights"-->  Spotify's servers
    E.V.E.  <--"that's spotify:track:0Vj..."--
    E.V.E.  --"play that on Chris's PC"-->  Spotify's servers  -->  the Spotify app on this PC

One-time setup (see SETUP below, or run the login command and it explains):
  1. Make a free "app" for E.V.E. on Spotify's developer site, and put its
     Client ID in .env as SPOTIFY_CLIENT_ID=...
  2. Run  .venv\\Scripts\\python -m actions.spotify login
     Your browser opens Spotify's own "allow E.V.E.?" page; click Agree.
     E.V.E. never sees your Spotify password.
  3. Her login is saved in data/spotify_token.json (data/ is never uploaded)
     and renews itself, so you don't do this again.

What she's allowed to do (the "scopes" below): control playback, see what's
playing, and read your playlists. Nothing else: she can't change playlists,
follow people or touch your account.

She always plays on THIS PC's Spotify, never your phone by accident. If
Spotify isn't open, she opens it and waits for it to connect first.

Test it alone:
    .venv\\Scripts\\python -m actions.spotify login           (once)
    .venv\\Scripts\\python -m actions.spotify devices         (is this PC's Spotify connected?)
    .venv\\Scripts\\python -m actions.spotify play blinding lights
    .venv\\Scripts\\python -m actions.spotify play artist arctic monkeys
    .venv\\Scripts\\python -m actions.spotify queue mr brightside
    .venv\\Scripts\\python -m actions.spotify now             (what's playing?)
"""

import difflib
import logging
import os
import socket
import time

import spotipy
from spotipy.cache_handler import CacheFileHandler
from spotipy.oauth2 import SpotifyOauthError, SpotifyPKCE

from actions import settings
from paths import DATA_DIR

diary = logging.getLogger("eve")

TOKEN_FILE = DATA_DIR / "spotify_token.json"
# Where Spotify's "allow E.V.E.?" page sends the browser back to, during login
# only. It must be typed EXACTLY like this in the app on Spotify's site.
REDIRECT_URI = "http://127.0.0.1:8888/callback"
# What she's allowed to do. Changing this means logging in again.
SCOPES = "user-read-playback-state user-modify-playback-state user-read-currently-playing playlist-read-private"
CONNECT_SECONDS = 15   # how long to wait for Spotify to connect after opening it

SETUP = f"""Spotify setup (one time, about 5 minutes):
  1. Go to https://developer.spotify.com/dashboard and log in with your Spotify account.
  2. Click "Create app". Name: E.V.E.  Description: my desktop assistant.
     Redirect URI: {REDIRECT_URI}   (type it exactly, then click Add)
     Tick "Web API", agree to the terms, and Save.
  3. Open the app's Settings and copy the Client ID (NOT the client secret).
  4. Add this line to E.V.E.'s .env file:   SPOTIFY_CLIENT_ID=<the Client ID>
  5. Run:  .venv\\Scripts\\python -m actions.spotify login"""

# What she says when she can't use Spotify yet.
NOT_SET_UP = "Spotify isn't set up for me yet, sir. The setup steps are in my Spotify file."
NOT_LOGGED_IN = "I'm not logged in to Spotify, sir. Run the Spotify login command once and I'll be sorted."

KINDS = {"song": "track", "track": "track", "artist": "artist", "album": "album", "playlist": "playlist"}


class NotReady(Exception):
    """Spotify can't be used right now. `say` is what she tells sir."""

    def __init__(self, problem: str, say: str):
        super().__init__(problem)
        self.say = say


# --- Logging in -------------------------------------------------------------

def _login_helper(open_browser: bool = False) -> SpotifyPKCE:
    """
    spotipy's login helper. "PKCE" is the kind of login meant for apps on
    your own PC: it needs only the Client ID, no secret password.
    """
    client_id = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
    if not client_id:
        raise NotReady("SPOTIFY_CLIENT_ID is missing from .env", NOT_SET_UP)
    return SpotifyPKCE(client_id=client_id, redirect_uri=REDIRECT_URI, scope=SCOPES,
                       cache_handler=CacheFileHandler(cache_path=str(TOKEN_FILE)),
                       open_browser=open_browser)


def _spotify() -> spotipy.Spotify:
    """
    A connection to Spotify using the saved login, renewed if it's run out.
    Never opens a browser or waits for typing: E.V.E. runs this in the
    background, where nobody would see it. Logging in is the login command's job.
    """
    helper = _login_helper()
    try:
        token = helper.validate_token(helper.cache_handler.get_cached_token())
    except SpotifyOauthError as error:   # e.g. you removed E.V.E.'s access on Spotify's site
        raise NotReady(f"Spotify login no longer works: {error}", NOT_LOGGED_IN) from error
    if not token:
        raise NotReady("not logged in to Spotify", NOT_LOGGED_IN)
    return spotipy.Spotify(auth=token["access_token"], requests_timeout=10, retries=1)


def login() -> None:
    """The one-time login, run from the command line. Opens your browser."""
    if not os.getenv("SPOTIFY_CLIENT_ID", "").strip():
        print(SETUP)
        return
    print("Opening Spotify's login page in your browser. Click Agree, then come back here.")
    helper = _login_helper(open_browser=True)
    helper.get_access_token()
    print(f"Logged in. Saved in {TOKEN_FILE}")
    me = spotipy.Spotify(auth_manager=helper).current_user()
    print(f"Spotify account: {me.get('display_name') or me.get('id')}")
    # (Spotify only says whether it's Premium with an extra permission she doesn't
    # ask for; without Premium, playing a song gives a clear "needs Premium" error.)


# --- This PC's Spotify ---------------------------------------------------------

def _this_pc(sp: spotipy.Spotify) -> dict | None:
    """This PC's Spotify app, as Spotify's servers see it (or None if it's not connected)."""
    computers = [d for d in sp.devices().get("devices", []) if d.get("type") == "Computer"]
    here = socket.gethostname().lower()
    for device in computers:   # Spotify names the PC's app after the PC
        if device.get("name", "").lower() == here:
            return device
    # Some PCs show a different name; one computer is surely this one.
    return computers[0] if len(computers) == 1 else None


def _device(sp: spotipy.Spotify) -> dict:
    """This PC's Spotify, opening the app and waiting for it to connect if needed."""
    device = _this_pc(sp)
    if device:
        return device
    from actions.apps import launch   # opens Spotify the same way open_app does
    try:
        # The Start Menu shortcut, like double-clicking it. (Opening a
        # "spotify:" link makes Spotify run its installer first.)
        launch("start menu: Spotify")
    except Exception as error:
        raise NotReady(f"couldn't open Spotify: {error}",
                       "I couldn't open Spotify on this PC, sir.") from error
    diary.info("[ACTION] Opened Spotify, waiting for it to connect")
    deadline = time.monotonic() + CONNECT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(1)
        device = _this_pc(sp)
        if device:
            return device
    raise NotReady("Spotify opened but didn't connect in time",
                   "Spotify's opening, sir, but it hasn't connected yet. Ask me again in a moment.")


# --- Finding music --------------------------------------------------------------

def _describe(item: dict) -> str:
    """ "Blinding Lights by The Weeknd", "AM by Arctic Monkeys", "Arctic Monkeys"... """
    name = item.get("name", "something")
    people = item.get("artists") or ([item["owner"]] if item.get("owner") else [])
    who = ", ".join(p.get("name") or p.get("display_name") or "" for p in people[:2]).strip(", ")
    if item.get("type") == "playlist":
        return f"your {name} playlist" if item.get("_mine") else f"the {name} playlist"
    return f"{name} by {who}" if who and item.get("type") != "artist" else name


def _my_playlist(sp: spotipy.Spotify, wanted: str) -> dict | None:
    """One of sir's own playlists that fits the name ("gym" -> "Gym Bangers"), or None."""
    key = settings.simplify(wanted.replace("playlist", ""))
    if not key:
        return None
    best, best_score = None, 0.0
    page = sp.current_user_playlists(limit=50)
    for _ in range(4):   # up to 200 playlists
        for playlist in (page or {}).get("items") or []:
            if not playlist:
                continue
            name = settings.simplify(playlist.get("name", ""))
            score = 1.0 if name == key else 0.9 if key in name else \
                difflib.SequenceMatcher(None, key, name).ratio()
            if score > best_score:
                best, best_score = playlist, score
        if not (page or {}).get("next"):
            break
        page = sp.next(page)
    if best and best_score >= 0.8:
        best["_mine"] = True
        return best
    return None


def _find(sp: spotipy.Spotify, query: str, kind: str) -> dict | None:
    """The best match for `query` on Spotify (its own ranking), or None."""
    if kind == "playlist":
        mine = _my_playlist(sp, query)
        if mine:
            return mine
    found = sp.search(q=query, type=kind, limit=5)
    items = [item for item in (found.get(f"{kind}s") or {}).get("items") or [] if item]
    return items[0] if items else None


def _kind(kind: str) -> str:
    return KINDS.get(str(kind).strip().lower(), "track")


# --- The tools ------------------------------------------------------------------

def play_music(query: str, kind: str = "song") -> dict:
    """
    Play a song, artist, album or playlist on Spotify on sir's PC. Use it
    whenever sir asks you to play some music and names what: "play Blinding
    Lights", "play some Arctic Monkeys", "play the album AM", "play my gym
    playlist". (To pause, resume or skip whatever's playing, use control_media.)

    Args:
        query: What to play, as sir said it, e.g. "blinding lights", "arctic
               monkeys", "AM arctic monkeys", "gym". Include the artist if he
               said one ("mr brightside the killers").
        kind: "song" (the default), "artist", "album" or "playlist".
    """
    kind = _kind(kind)
    try:
        sp = _spotify()
        item = _find(sp, query, kind)
        if not item:
            return {"error": f"nothing on Spotify for {query}",
                    "say": f"I couldn't find {query} on Spotify, sir."}
        device = _device(sp)
        if kind == "track":
            sp.start_playback(device_id=device["id"], uris=[item["uri"]])
        else:
            sp.start_playback(device_id=device["id"], context_uri=item["uri"])
    except NotReady as problem:
        return {"error": str(problem), "say": problem.say}
    except spotipy.SpotifyException as error:
        return _spotify_error(error)
    what = _describe(item)
    return {"playing": what, "say": f"Playing {what}, sir."}


def queue_song(query: str) -> dict:
    """
    Add a song to sir's Spotify queue, to play after the current one. Use it
    when sir says "queue", "add ... to the queue" or "play ... next". If
    nothing is playing, it just plays the song.

    Args:
        query: The song, as sir said it, with the artist if he said one,
               e.g. "mr brightside the killers".
    """
    try:
        sp = _spotify()
        song = _find(sp, query, "track")
        if not song:
            return {"error": f"nothing on Spotify for {query}",
                    "say": f"I couldn't find {query} on Spotify, sir."}
        device = _device(sp)
        what = _describe(song)
        playing = sp.current_playback() or {}
        if not playing.get("is_playing"):   # nothing playing: a queue would just sit there
            sp.start_playback(device_id=device["id"], uris=[song["uri"]])
            return {"playing": what, "say": f"Nothing was playing, so I've put on {what}, sir."}
        sp.add_to_queue(song["uri"], device_id=device["id"])
    except NotReady as problem:
        return {"error": str(problem), "say": problem.say}
    except spotipy.SpotifyException as error:
        return _spotify_error(error)
    return {"queued": what, "say": f"{what} is up next, sir."}


def whats_playing() -> dict:
    """
    What's playing on sir's Spotify right now: the song and artist. Use it
    when sir asks "what song is this?", "who sings this?" or "what's playing?".
    """
    try:
        playing = _spotify().current_playback() or {}
    except NotReady as problem:
        return {"error": str(problem), "say": problem.say}
    except spotipy.SpotifyException as error:
        return _spotify_error(error)
    song = playing.get("item")
    if not song:
        return {"playing": None, "say": "Nothing's playing on Spotify right now, sir."}
    what = _describe(song)
    if not playing.get("is_playing"):
        return {"paused": what, "say": f"{what} is paused, sir."}
    return {"playing": what, "say": f"This is {what}, sir."}


def _spotify_error(error: spotipy.SpotifyException) -> dict:
    """Turn an error from Spotify into something she can say."""
    diary.warning(f"Spotify said no: {error.http_status} {error.msg}")
    if error.http_status == 403 and "scope" in str(error.msg).lower():
        say = "Spotify says I'm missing a permission, sir. Run the Spotify login command again."
    elif error.http_status == 403:
        say = "Spotify won't let me control playback, sir. That needs Premium."
    elif error.http_status == 404:
        say = "Spotify on this PC isn't responding, sir. Try opening it and asking again."
    elif error.http_status == 429:
        say = "Spotify's asked me to slow down, sir. Give it a minute."
    else:
        say = "Spotify gave me an error, sir. The log has the details."
    return {"error": f"Spotify error {error.http_status}: {error.msg}", "say": say}


# --- Testing from the command line ------------------------------------------------

if __name__ == "__main__":
    import json
    import sys

    from dotenv import load_dotenv

    from paths import BASE_DIR

    load_dotenv(BASE_DIR / ".env")
    words = sys.argv[1:]
    command = words[0] if words else ""
    if command == "login":
        login()
    elif command == "devices":
        try:
            sp = _spotify()
            for d in sp.devices().get("devices", []):
                print(f"  {d['name']}  ({d['type']}){'  <- playing' if d.get('is_active') else ''}")
            print(f"This PC is called {socket.gethostname()}. Chosen: {(_this_pc(sp) or {}).get('name', 'none connected')}")
        except NotReady as problem:
            print(problem.say, f"({problem})")
    elif command == "play" and words[1:]:
        kind = words[1] if words[1] in KINDS else "song"
        query = " ".join(words[2:] if words[1] in KINDS else words[1:])
        print(json.dumps(play_music(query, kind), indent=2, ensure_ascii=False))
    elif command == "queue" and words[1:]:
        print(json.dumps(queue_song(" ".join(words[1:])), indent=2, ensure_ascii=False))
    elif command == "now":
        print(json.dumps(whats_playing(), indent=2, ensure_ascii=False))
    else:
        print(__doc__)
        print(SETUP)
