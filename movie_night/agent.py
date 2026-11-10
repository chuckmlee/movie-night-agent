"""M2: the movie night agent, v1. Polls one Linq group chat.

    python3 -m movie_night.agent run --chat <chat_id>          # live
    python3 -m movie_night.agent run --chat <chat_id> --dry-run  # print, don't send

Flow, per DECISIONS.md:
1. Someone kicks off ("movie night?", "movie tonight, something short", "movie?", 🎬).
   The agent only ever speaks after a kickoff like that.
2. It reads hints from that message, picks 4-5 films from the synced watchlist,
   and sends each as a text followed by its trailer link.
3. People react 🥇 🥈 🥉 and veto with 🚫 or 👎. The tally is code (rules.py).
4. When everyone has given a 🥇, or someone texts "tally" / "done", it announces
   the winner and why. It records vetoes and top picks for next time.

State lives in data/ (git-ignored): agent-state.json and history.json.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import linq_format
from .picker import choose, parse_hints
from .rules import Film, History, Reaction, ReactionEvent, Session

LINQ = "https://api.linqapp.com/api/partner/v3"
DATA = Path("data")
# Deliberately narrow, so "great movie!" after a session doesn't start another one.
KICKOFF_RE = re.compile(
    r"\bmovie\s+(night|tonight|time)\b|\bmovies?\s*\?|\bpick\s+(us\s+)?a\s+movie\b|^\s*movie\s*$|🎬", re.I)
TALLY_RE = re.compile(r"^\s*(tally|done|count|results?|pick it|decide)\b", re.I)
RECENT_SESSIONS_EXCLUDED = 3


class Linq:
    def __init__(self, token: str | None = None, dry_run: bool = False):
        self.token = token or "injected-by-proxy"
        self.dry_run = dry_run
        self._fake = 0

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(
            LINQ + path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read() or b"{}")

    def messages(self, chat_id: str) -> list[dict]:
        """Oldest first."""
        msgs = self._call("GET", f"/chats/{chat_id}/messages").get("messages", [])
        return sorted(msgs, key=lambda m: m.get("created_at") or "")

    def send(self, chat_id: str, body: dict) -> str:
        if self.dry_run:
            parts = body["message"]["parts"]
            print("SEND:", " | ".join(p["value"] for p in parts))
            self._fake += 1
            return f"dry-{self._fake}"
        return self._call("POST", f"/chats/{chat_id}/messages", body)["message"]["id"]

    def say(self, chat_id: str, text: str) -> str:
        return self.send(chat_id, {"message": {"parts": [{"type": "text", "value": text}]}})


@dataclass
class State:
    seen: list[str] = field(default_factory=list)  # message ids already handled
    active: dict | None = None  # {"kickoff_id", "films": [slug], "msg_to_slug": {id: slug}, "started"}

    @classmethod
    def load(cls, path: Path) -> "State":
        return cls(**json.loads(path.read_text())) if path.exists() else cls()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.__dict__, indent=1))


def _text(m: dict) -> str:
    return " ".join(p.get("value") or "" for p in m.get("parts") or [] if p.get("type") == "text")


def _people(msgs: list[dict]) -> list[str]:
    return sorted({h["handle"] for m in msgs for h in [m.get("from_handle") or {}] if h and not h.get("is_me")})


def load_history(path: Path) -> list[dict]:
    return json.loads(path.read_text()) if path.exists() else []


def history_for(sessions: list[dict]) -> History:
    if not sessions:
        return History()
    last = sessions[-1]
    return History(vetoed_last_session=set(last.get("vetoed_by", [])),
                   missed_top_pick_last_session=set(last.get("missed_top_pick", [])))


def build_session(active: dict, cache: dict, msgs: list[dict], people: list[str], hist: History) -> Session:
    films = [Film(s, cache[s]["title"], cache[s].get("letterboxd_rating")) for s in active["films"]]
    session = Session(films, people, hist)
    # Rebuild from the reactions currently on the messages, so a removed
    # reaction simply disappears. Linq gives no reaction timestamps, so if
    # someone put the same medal on two films, the later film in the list wins.
    for m in msgs:
        slug = active["msg_to_slug"].get(m["id"])
        if not slug:
            continue
        for handle, reaction in linq_format.parse_reactions(m).votes:
            session.apply(ReactionEvent(handle, slug, reaction))
    return session


def explain(result, cache: dict, names: dict[str, str]) -> str:
    if result.all_vetoed:
        return "Everything got vetoed 😅 Say \"movie\" again and I'll send a fresh set."
    if result.winner is None:
        return "No votes yet."
    top = result.scores[0]
    title = cache[top.film.film_id]["title"]
    parts = "+".join(str(top.per_person[p]) for p in sorted(top.per_person))
    line = f"🏆 Tonight: {title} ({parts} = {top.total})"
    if result.tie_break:
        line += f"\nTie broken by {result.tie_break.split(': ', 1)[-1]}."
    vetoes = [s for s in result.scores if s.vetoed_by]
    if vetoes:
        line += "\nVetoed: " + ", ".join(cache[s.film.film_id]["title"] for s in vetoes)
    for event, why in result.rejected:
        who = names.get(event.person, event.person)
        line += f"\n(Didn't count {who}'s {event.reaction.value}: {why}.)"
    return line


def reason_for(entry: dict) -> str | None:
    """v1 "why": the Letterboxd rating. An LLM-written line can replace this later."""
    r = entry.get("letterboxd_rating")
    return f"★ {r:.1f} on Letterboxd" if r else None


def everyone_gave_gold(session: Session) -> bool:
    return all(Reaction.GOLD in session.state[p] for p in session.people)


def step(linq: Linq, chat_id: str, state: State, cache: dict, history: list[dict],
         names: dict[str, str] | None = None, seed: int | None = None) -> str | None:
    """One poll. Returns what happened, for logging."""
    names = names or {}
    msgs = linq.messages(chat_id)
    people = _people(msgs)
    new = [m for m in msgs if m["id"] not in state.seen and not (m.get("from_handle") or {}).get("is_me")]
    for m in msgs:
        if m["id"] not in state.seen:
            state.seen.append(m["id"])

    if state.active is None:
        kick = next((m for m in reversed(new) if KICKOFF_RE.search(_text(m))), None)
        if not kick:
            return None
        hints = parse_hints(_text(kick))
        recent = {s for h in history[-RECENT_SESSIONS_EXCLUDED:] for s in h.get("films", [])}
        slugs = choose(cache, hints, n=5, exclude=recent, seed=seed)
        if not slugs and not hints.allow_rent:
            hints.allow_rent = True
            slugs = choose(cache, hints, n=5, exclude=recent, seed=seed)
        if not slugs:
            linq.say(chat_id, "I couldn't find anything on the watchlist that fits. Try fewer limits?")
            return "kickoff: nothing fit"
        hist = history_for(history)
        no_veto = [names.get(p, p) for p in people if p in hist.vetoed_last_session]
        intro = f"🍿 {len(slugs)} picks from the watchlist. React 🥇 🥈 🥉, veto with 👎."
        if no_veto:
            intro += f" ({', '.join(no_veto)}: no veto tonight, you used one last time.)"
        linq.say(chat_id, intro)
        msg_to_slug = {}
        for slug in slugs:
            for body in linq_format.pick_messages(linq_format.pick_from_cache(cache[slug], reason_for(cache[slug]))):
                msg_to_slug[linq.send(chat_id, body)] = slug
        state.active = {"kickoff_id": kick["id"], "films": slugs, "msg_to_slug": msg_to_slug,
                        "started": dt.datetime.now(dt.timezone.utc).isoformat()}
        return f"kickoff: sent {len(slugs)} picks"

    session = build_session(state.active, cache, msgs, people, history_for(history))
    asked = any(TALLY_RE.search(_text(m)) for m in new)
    if not (asked or everyone_gave_gold(session)):
        return None
    result = session.tally()
    linq.say(chat_id, explain(result, cache, names))
    tops = session.top_picks()
    history.append({
        "date": dt.date.today().isoformat(),
        "films": state.active["films"],
        "winner": result.winner.film_id if result.winner else None,
        "vetoed_by": sorted({p for s in result.scores for p in s.vetoed_by}),
        "missed_top_pick": sorted(p for p, g in tops.items() if g and result.winner and g != result.winner.film_id),
    })
    state.active = None
    return "tally: " + (result.winner.film_id if result.winner else "no winner")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(required=True)
    r = sub.add_parser("run")
    r.add_argument("--chat", required=True)
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--every", type=float, default=5.0, help="seconds between polls")
    r.add_argument("--once", action="store_true")
    r.add_argument("--data", type=Path, default=DATA)
    args = ap.parse_args(argv)

    cache = json.loads((args.data / "films.json").read_text())
    state_path, hist_path = args.data / "agent-state.json", args.data / "history.json"
    linq = Linq(dry_run=args.dry_run)
    state = State.load(state_path)
    history = load_history(hist_path)
    if not state.seen:
        # First run: ignore everything already in the chat.
        state.seen = [m["id"] for m in linq.messages(args.chat)]
        state.save(state_path)
    while True:
        try:
            what = step(linq, args.chat, state, cache, history)
        except urllib.error.URLError as e:
            what = f"poll failed: {e}"
        if what:
            print(dt.datetime.now().strftime("%H:%M:%S"), what, file=sys.stderr)
        state.save(state_path)
        hist_path.write_text(json.dumps(history, indent=1))
        if args.once:
            break
        time.sleep(args.every)


if __name__ == "__main__":
    main()
