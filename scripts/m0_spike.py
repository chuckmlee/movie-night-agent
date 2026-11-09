"""M0: Linq spike. Does a real iMessage group chat deliver medal and veto reactions?

Steps:
  1. `numbers`  list the Linq lines on the account (and confirm the token works)
  2. `group`    create a group chat with the household phones and send a test pick
  3. `poll`     print every message and reaction in that chat, raw, so we can
                see whether reactions arrive as the emoji people tapped
  4. `serve`    run a tiny webhook receiver that logs raw events (needs a public
                HTTPS URL in front of it; see docs/m0-linq-spike.md)

Phone numbers come from the environment (MNA_PHONES, comma separated) and are
never committed. Auth is injected by the session proxy for api.linqapp.com;
outside that, set LINQ_TOKEN.

Endpoint shapes follow Linq's v3 partner API docs, but have not yet been
checked against a live account: the first `numbers` run is that check.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

BASE = os.environ.get("LINQ_BASE", "https://api.linqapp.com/api/partner/v3")
TEST_PICK = (
    "Movie night test 🎬 React to this message with 🥇 🥈 🥉 or 🚫 (long-press, then the + for any emoji).\n"
    "Arrival (2016) · 1h 56m\n"
    "Trailer: https://www.youtube.com/results?search_query=Arrival+2016+trailer"
)


def call(method: str, path: str, body: dict | None = None) -> dict:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    token = os.environ.get("LINQ_TOKEN")
    # The proxy replaces this header in the cloud session; locally it is the real token.
    headers["Authorization"] = f"Bearer {token or 'injected-by-proxy'}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {path} -> HTTP {e.code}: {e.read().decode()[:500]}")


def cmd_numbers(_):
    print(json.dumps(call("GET", "/phone_numbers"), indent=2))


def cmd_group(args):
    phones = [p.strip() for p in os.environ.get("MNA_PHONES", "").split(",") if p.strip()]
    if len(phones) < 2:
        sys.exit("set MNA_PHONES to at least two E.164 numbers, comma separated")
    body = {"to": phones, "message": {"parts": [{"type": "text", "value": TEST_PICK}]}}
    if args.from_number:
        body["from"] = args.from_number
    out = call("POST", "/chats", body)
    print(json.dumps(out, indent=2))


def cmd_poll(args):
    print(json.dumps(call("GET", f"/chats/{args.chat_id}/messages"), indent=2))


class Hook(BaseHTTPRequestHandler):
    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        with open("m0-webhook-events.jsonl", "ab") as f:
            f.write(raw + b"\n")
        print(raw.decode(errors="replace"), flush=True)
        self.send_response(200)
        self.end_headers()


def cmd_serve(args):
    print(f"logging webhook POSTs to m0-webhook-events.jsonl on :{args.port}")
    HTTPServer(("0.0.0.0", args.port), Hook).serve_forever()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(required=True)
    sub.add_parser("numbers").set_defaults(fn=cmd_numbers)
    g = sub.add_parser("group")
    g.add_argument("--from-number", help="Linq line to send from, if the account has several")
    g.set_defaults(fn=cmd_group)
    p = sub.add_parser("poll")
    p.add_argument("chat_id")
    p.set_defaults(fn=cmd_poll)
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8787)
    s.set_defaults(fn=cmd_serve)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
