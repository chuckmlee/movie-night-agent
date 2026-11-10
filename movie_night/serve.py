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
  MNA_CHAT_ID              the household group chat id
  MNA_LETTERBOXD_USER      whose watchlist (default: chucklee)
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

from . import sync as sync_mod
from .agent import Linq, State, load_history, step, tmdb_lookup

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


def run_sync(user: str, data: Path) -> None:
    try:
        stats = sync_mod.sync(user, data, log=log)
        STATUS["last_sync"] = {"at": dt.datetime.now(dt.timezone.utc).isoformat(), **stats}
    except Exception as e:  # a failed sync must not take the agent down
        STATUS["errors"] += 1
        log(f"sync failed: {e!r}")


def sync_loop(user: str, data: Path, hour: int) -> None:
    cache_path = data / "films.json"
    stale = not cache_path.exists()
    if not stale:  # a cache from before topic search has no keywords yet
        cache = json.loads(cache_path.read_text())
        stale = any(e.get("tmdb_id") and "keywords" not in e for e in cache.values())
    if stale:
        run_sync(user, data)
    while True:
        now = dt.datetime.now(dt.timezone.utc)
        nxt = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if nxt <= now:
            nxt += dt.timedelta(days=1)
        time.sleep((nxt - now).total_seconds())
        run_sync(user, data)


def agent_loop(chat: str, data: Path, every: float) -> None:
    linq = Linq(token=os.environ.get("LINQ_TOKEN"))
    state_path, hist_path = data / "agent-state.json", data / "history.json"
    while not (data / "films.json").exists():
        time.sleep(10)  # first boot: wait for the initial sync
    state = State.load(state_path)
    history = load_history(hist_path)
    if not state.seen:
        state.seen = [m["id"] for m in linq.messages(chat)]
        state.save(state_path)
        log(f"agent: watching chat, {len(state.seen)} existing messages skipped")
    while True:
        try:
            cache = json.loads((data / "films.json").read_text())  # picks up the daily sync
            what = step(linq, chat, state, cache, history, lookup=tmdb_lookup)
            STATUS["last_poll"] = dt.datetime.now(dt.timezone.utc).isoformat()
            if what:
                STATUS["last_event"] = what
                log(f"agent: {what}")
            state.save(state_path)
            hist_path.write_text(json.dumps(history, indent=1))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            STATUS["errors"] += 1
            log(f"agent: poll failed: {e!r}")
        time.sleep(every)


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
    agent = threading.Thread(target=agent_loop, args=(chat, data, every), daemon=True, name="agent")
    agent.start()

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
