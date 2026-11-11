"""Hosted entry point: one process that runs the whole agent.

    python3 -m movie_night.serve

- Polls the household chat (the same loop as `movie_night.agent run`).
- Runs the watchlist sync on boot if there's no film cache yet, then daily at
  SYNC_HOUR_UTC.
- Serves GET /health on $PORT, so the host can tell it's alive. POST /linq is
  a placeholder that logs Linq webhook events raw; polling stays the source of
  truth until webhooks are proven.

Config comes from the environment (set on the host, never committed):
  LINQ_TOKEN, TMDB_TOKEN   API credentials
  ANTHROPIC_API_KEY        optional: lets Claude read the circle's reviews for quotes
  OMDB_API_KEY             optional: IMDb, Rotten Tomatoes and Metacritic for the quality score
  MNA_CHAT_ID              the household group chat id
  MNA_TEST_CHAT_ID         optional: a second chat (e.g. just you and Delo) for testing; its sessions,
                           vetoes and history live in data/test/ and never affect the household's
  MNA_LETTERBOXD_USER      whose watchlist and ratings (default: chucklee)
  MNA_LETTERBOXD_EXPORT    unzipped Letterboxd data export, for the full rating
                           history (default: $MNA_DATA/letterboxd-export, then
                           household/letterboxd in the repo, if either exists)
  MNA_DATA                 persistent directory (default: data; mount a volume here)
  SYNC_HOUR_UTC            default 10 (5 or 6am in New York)
  PORT                     default 8080
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import threading
import time
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import emoji as emoji_mod
from .ask import Asker
from . import circle as circle_mod
from . import discover
from . import sync as sync_mod
from . import quality as quality_mod
from .seen import FreshSeen
from . import taste as taste_mod
from . import tmdb
from .agent import Linq, State, load_history, step, tmdb_lookup

SYNC_READY = threading.Event()  # set once the film cache is complete and current
STATUS = {"started": dt.datetime.now(dt.timezone.utc).isoformat(), "last_poll": None, "last_sync": None,
          "last_event": None, "errors": 0}


def log(msg: str) -> None:
    print(dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), msg, file=sys.stderr, flush=True)


class Handler(BaseHTTPRequestHandler):
    data: Path = Path("data")

    def do_GET(self):
        if self.path != "/health":
            self.send_error(404)
            return
        body = json.dumps(STATUS).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/linq":
            self.send_error(404)
            return
        size = int(self.headers.get("Content-Length", 0))
        if size > 65536:  # unauthenticated for now, so keep it from filling the disk
            self.send_error(413)
            return
        raw = self.rfile.read(size)
        with open(self.data / "webhook-events.jsonl", "ab") as f:
            f.write(raw + b"\n")
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):  # keep health checks out of the logs
        pass


def export_dir(data: Path) -> Path | None:
    for cand in (os.environ.get("MNA_LETTERBOXD_EXPORT"), data / "letterboxd-export",
                 Path(__file__).resolve().parent.parent / "household" / "letterboxd"):
        if cand and (Path(cand) / "ratings.csv").exists():
            return Path(cand)
    return None


def run_sync(user: str, data: Path) -> None:
    try:
        stats = sync_mod.sync(user, data, log=log)
        STATUS["last_sync"] = {"at": dt.datetime.now(dt.timezone.utc).isoformat(), **stats}
    except Exception as e:  # a failed sync must not take the agent down
        STATUS["errors"] += 1
        log(f"sync failed: {e!r}")
    try:  # reviews from the people you follow; the profile works without them
        store = circle_mod.refresh(user, data, log=log)
        STATUS["last_circle"] = {"people": len(store.get("people", [])), "reviews": len(store.get("reviews", {})),
                                 "extracted": sum(1 for r in store.get("reviews", {}).values() if r.get("extract"))}
    except Exception as e:
        STATUS["errors"] += 1
        log(f"circle refresh failed: {e!r}")
    try:  # the taste profile reads the fresh cache; picks fall back to ratings without it
        out = taste_mod.build(user, data, export=export_dir(data), log=log)
        STATUS["last_taste"] = {"at": out["built"], "rated": out["rated"], "wildcards": len(out["wildcards"])}
    except Exception as e:
        STATUS["errors"] += 1
        log(f"taste profile failed: {e!r}")
    try:  # IMDb / Rotten Tomatoes / Metacritic via OMDb, then the blended score; picks work without it
        films = json.loads((data / "films.json").read_text())
        films.update((taste_mod.load(data) or {}).get("wildcards") or {})
        quality_mod.refresh(films, data, log=log)
        q = quality_mod.build(films, data, log=log)
        STATUS["last_quality"] = {"scored": len(q)}
    except Exception as e:
        STATUS["errors"] += 1
        log(f"quality score failed: {e!r}")


def sync_loop(user: str, data: Path, hour: int) -> None:
    cache_path = data / "films.json"
    stale = not cache_path.exists() or not (data / "sync-complete.json").exists()
    if not stale:  # a cache from before topic search has no keywords yet
        cache = json.loads(cache_path.read_text())
        missing = sum(1 for e in cache.values() if e.get("tmdb_id") and "keywords" not in e)
        stale = missing > 0.05 * max(len(cache), 1)
    if cache_path.exists():
        SYNC_READY.set()  # answer from the cache we have while the sync catches up
    if stale:
        run_sync(user, data)
    elif not (data / "taste.json").exists():
        run_sync(user, data)  # first boot with taste: build it now, not tomorrow
    SYNC_READY.set()
    while True:
        now = dt.datetime.now(dt.timezone.utc)
        nxt = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if nxt <= now:
            nxt += dt.timedelta(days=1)
        time.sleep((nxt - now).total_seconds())
        run_sync(user, data)


def check_tokens(linq: Linq) -> None:
    """Say plainly at boot whether each key works, instead of a traceback later."""
    try:
        linq.phone_numbers()
        log("check: LINQ_TOKEN ok")
    except urllib.error.HTTPError as e:
        log(f"check: LINQ_TOKEN rejected by Linq (HTTP {e.code}). Set it to the raw key, without 'Bearer'.")
    except urllib.error.URLError as e:
        log(f"check: couldn't reach Linq: {e!r}")
    try:
        tmdb._get("/configuration")
        log("check: TMDB_TOKEN ok")
    except urllib.error.HTTPError as e:
        log(f"check: TMDB_TOKEN rejected by TMDB (HTTP {e.code}). Use the long Read Access Token (eyJ...), raw.")
    except urllib.error.URLError as e:
        log(f"check: couldn't reach TMDB: {e!r}")


def agent_loop(chat: str, data: Path, every: float, user: str = "chucklee", state_dir: Path | None = None,
               check: bool = True) -> None:
    """Watch one chat. `state_dir` keeps a test chat's sessions, vetoes and history apart from the household's."""
    linq = Linq(token=os.environ.get("LINQ_TOKEN"))
    state_dir = state_dir or data
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path, hist_path = state_dir / "agent-state.json", state_dir / "history.json"
    tag = "agent-test" if state_dir != data else "agent"
    if check:
        check_tokens(linq)
    if not SYNC_READY.is_set():
        log(f"{tag}: waiting for the first watchlist sync to finish")
    SYNC_READY.wait()
    state = State.load(state_path)
    history = load_history(hist_path)
    backoff = every
    emojis = emoji_mod.Emojis(data / "emoji.json", log=log)
    asker = Asker(log=log)
    seen = FreshSeen(user, log=log)
    while True:
        try:
            if not state.seen:
                state.seen = [m["id"] for m in linq.messages(chat)]
                state.save(state_path)
                log(f"{tag}: watching chat, {len(state.seen)} existing messages skipped")
            cache = json.loads((data / "films.json").read_text())  # picks up the daily sync
            taste = taste_mod.load(data)
            if taste:
                cache.update(taste.get("wildcards") or {})
            try:  # rated or logged since the 5 AM rebuild: don't offer it again today
                seen.drop(cache, keep=(state.active or {}).get("films", []))
            except Exception as e:
                log(f"seen: skipped this poll: {e!r}")
            try:  # scores are a nicety; never let them stop the agent (Nov 11 crash loop)
                quality_mod.annotate(cache, quality_mod.load(data))
            except Exception as e:
                log(f"quality: skipped this poll: {e!r}")
            try:  # "new on Netflix since Nov 3": from the daily availability snapshots
                discover.annotate(cache, data)
            except Exception as e:
                log(f"discover: skipped this poll: {e!r}")
            what = step(linq, chat, state, cache, history, lookup=tmdb_lookup, taste=taste, emojis=emojis, ask=asker)
            STATUS["last_poll"] = dt.datetime.now(dt.timezone.utc).isoformat()
            if what:
                STATUS["last_event"] = what
                log(f"{tag}: {what}")
            state.save(state_path)
            hist_path.write_text(json.dumps(history, indent=1))
            backoff = every
        except urllib.error.HTTPError as e:
            STATUS["errors"] += 1
            hint = " (check LINQ_TOKEN)" if e.code in (401, 403) else ""
            log(f"{tag}: Linq returned HTTP {e.code}{hint}; retrying in {backoff:.0f}s")
            backoff = min(backoff * 2, 300)  # don't hammer Linq with a bad key
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            STATUS["errors"] += 1
            log(f"{tag}: poll failed: {e!r}")
        time.sleep(backoff)


def main() -> None:
    chat = os.environ.get("MNA_CHAT_ID")
    if not chat:
        sys.exit("set MNA_CHAT_ID")
    for var in ("LINQ_TOKEN", "TMDB_TOKEN"):
        if not os.environ.get(var):
            log(f"warning: {var} is not set")
    data = Path(os.environ.get("MNA_DATA", "data"))
    data.mkdir(parents=True, exist_ok=True)
    user = os.environ.get("MNA_LETTERBOXD_USER", "chucklee")
    hour = int(os.environ.get("SYNC_HOUR_UTC", "10"))
    every = float(os.environ.get("POLL_SECONDS", "4"))

    threading.Thread(target=sync_loop, args=(user, data, hour), daemon=True, name="sync").start()
    agent = threading.Thread(target=agent_loop, args=(chat, data, every, user), daemon=True, name="agent")
    agent.start()
    test_chat = os.environ.get("MNA_TEST_CHAT_ID", "").strip()
    if test_chat and test_chat != chat:  # a private chat for trying Delo alone; it never touches the household's state
        threading.Thread(target=agent_loop, args=(test_chat, data, every, user, data / "test", False),
                         daemon=True, name="agent-test").start()
        log("agent: also watching the test chat")

    Handler.data = data
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    log(f"serving /health on :{port}")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    while agent.is_alive():
        time.sleep(5)
    log("agent thread died; exiting so the host restarts us")
    sys.exit(1)


if __name__ == "__main__":
    main()
