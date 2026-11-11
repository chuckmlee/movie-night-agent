"""M2: the movie night agent, v1. Polls one Linq group chat.

    python3 -m movie_night.agent run --chat <chat_id>          # live
    python3 -m movie_night.agent run --chat <chat_id> --dry-run  # print, don't send

Flow, per DECISIONS.md:
1. Someone kicks off ("movie night?", "movie tonight, something short", "movie?", 🎬).
   The agent only ever speaks after a kickoff like that.
2. It reads hints from that message, picks 4-5 films from the synced watchlist,
   and sends each as one message: the poster, then a short text.
3. People react 🥇 🥈 🥉 and veto with 🚫 or 👎, or by replying "veto, too bleak".
   Each veto brings one replacement (which can't be vetoed), chosen to avoid
   the reason. The tally is code (rules.py).
   A 👀 on a pick asks for its trailer, which Delo sends as a threaded reply.
4. When everyone has placed 🥇🥈🥉 (or has a 🥇 and stops changing reactions for
   90 seconds), or someone texts "tally" / "done", it announces
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

from . import emoji as emoji_mod, linq_format, tmdb
from .picker import plan
from .rules import Film, History, Reaction, ReactionEvent, Session

LINQ = "https://api.linqapp.com/api/partner/v3"
DATA = Path("data")
# Deliberately narrow, so "great movie!" after a session doesn't start another one.
ASK_RE = re.compile(
    r"\bmovie\s+(night|tonight|time)\b|\bmovies?\s*\?|\bpick\s+(us\s+)?a\s+movie\b|^\s*movie\s*$|🎬", re.I)
NAMED_RE = re.compile(r"^\s*(hey\s+|ok\s+)?delo\b", re.I)  # talking to Delo by name
KICKOFF_RE = re.compile(ASK_RE.pattern + "|" + NAMED_RE.pattern, re.I)
# "something a lot like The Wicker Man", "any movies similar to Heat": a request
# even without "movie night", as long as the title resolves on TMDB.
LIKE_KICKOFF_RE = re.compile(r"\b(something|anything|movies?|films?|ideas?)\b[^.?!]*\b(like|similar to|as good as)\b", re.I)
def _bare(text: str) -> str:
    """The message without a leading "hey Delo," so commands still match."""
    return re.sub(r"^\s*(hey\s+|ok\s+)?delo\b[\s,:]*", "", text, flags=re.I)


def _is_kickoff(text: str) -> bool:
    if TALLY_RE.search(_bare(text)):  # "delo, tally" counts votes; it isn't a new ask
        return False
    return bool(KICKOFF_RE.search(text) or LIKE_KICKOFF_RE.search(text))


# While picks are open, "limit to Catholic themes", "shorter", "less bleak" narrow
# the last ask instead of being ignored (Nov 10). Only openers that read as an
# instruction count, so chat between the two of them doesn't reshuffle picks.
REFINE_RE = re.compile(
    r"^\s*(limit|only|narrow|stick to|keep it|make it|same but|but|more|less|without|no|nothing|"
    r"shorter|longer|lighter|darker|funnier|newer|older|instead|rather|what about|how about|prefer|focus)\b",
    re.I)


def _is_refinement(text: str) -> bool:
    if TALLY_RE.search(_bare(text)):
        return False
    if REFINE_RE.search(_bare(text)):
        return True
    # "Delo, Catholic themes only": addressed by name, with a narrowing word, and not a new ask.
    return bool(NAMED_RE.search(text) and not ASK_RE.search(text) and not LIKE_KICKOFF_RE.search(text)
                and re.search(r"\b(only|limit|narrow|stick to|instead)\b", text, re.I))


TALLY_RE = re.compile(r"^\s*(tally|done|count|results?|pick it|decide)\b", re.I)
RECENT_SESSIONS_EXCLUDED = 3


def clean_token(token: str | None) -> str | None:
    """Accept a key pasted with "Bearer " or stray spaces/quotes; the header adds Bearer itself."""
    if not token:
        return None
    t = token.strip().strip('"').strip("'").strip()
    if t.lower().startswith("bearer "):
        t = t[7:].strip()
    return t or None


class Linq:
    def __init__(self, token: str | None = None, dry_run: bool = False):
        self.token = clean_token(token) or "injected-by-proxy"
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

    def phone_numbers(self) -> list[dict]:
        return self._call("GET", "/phone_numbers").get("phone_numbers", [])

    def members(self, chat_id: str) -> list[str]:
        """Everyone in the chat except the agent's own line."""
        chat = self._call("GET", f"/chats/{chat_id}")
        return sorted(h["handle"] for h in chat.get("handles", [])
                      if not h.get("is_me") and h.get("status", "active") == "active")

    def send(self, chat_id: str, body: dict) -> str:
        if self.dry_run:
            parts = body["message"]["parts"]
            print("SEND:", " | ".join(p.get("value") or p.get("url") or "" for p in parts))
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


def load_history(path: Path) -> list[dict]:
    return json.loads(path.read_text()) if path.exists() else []


def history_for(sessions: list[dict]) -> History:
    if not sessions:
        return History()
    last = sessions[-1]
    vetoed = set(last.get("vetoed_by", []))
    if last.get("people") and set(last["people"]) <= vetoed:
        vetoed = set()  # everyone vetoed: everyone paid, so nobody sits out (Chuck, Nov 11)
    return History(vetoed_last_session=vetoed,
                   missed_top_pick_last_session=set(last.get("missed_top_pick", [])))


def build_session(active: dict, cache: dict, msgs: list[dict], people: list[str], hist: History) -> Session:
    films = [Film(s, cache[s]["title"], cache[s].get("letterboxd_rating")) for s in active["films"]]
    session = Session(films, people, hist, protected=set(active.get("protected", [])))
    # Rebuild from the reactions currently on the messages, so a removed
    # reaction simply disappears. Linq gives no reaction timestamps, so if
    # someone put the same medal on two films, the later film in the list wins.
    for m in msgs:
        slug = active["msg_to_slug"].get(m["id"])
        if not slug:
            continue
        for handle, reaction in linq_format.parse_reactions(m).votes:
            session.apply(ReactionEvent(handle, slug, reaction))
    for handle, slug in active.get("text_vetoes", []):  # "veto, too bleak" as a reply
        session.apply(ReactionEvent(handle, slug, Reaction.VETO))
    return session


# A reply on a pick that opens like a veto: "veto because no war movies", "nah, too long", "👎 too bleak".
VETO_TEXT_RE = re.compile(r"^\s*(veto(ed)?|nah|nope|pass|hard pass|skip|not this( one)?|no|👎)\b[\s,:.!-]*", re.I)


def _reply_target(m: dict) -> str | None:
    r = m.get("reply_to")
    return (r.get("message_id") if isinstance(r, dict) else r) or None


TITLE_STOP = {"the", "a", "an", "of", "and", "in", "on", "with", "to", "me", "my", "for", "at"}


def _words(t: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", t.lower())


def find_named_pick(text: str, films: list[str], cache: dict) -> tuple[str, str] | None:
    """(slug, the words that named it): "fire walk with me" names "Twin Peaks: Fire Walk with Me".

    A full title or a part of it after a colon or dash counts; so does sharing
    two or more title words, or one long one ("lieutenant")."""
    said = " " + " ".join(_words(text)) + " "
    best = None
    for slug in films:
        title = cache.get(slug, {}).get("title") or ""
        for piece in [title, *re.split(r"\s*[:\u2013\u2014-]\s+", title)]:
            w = " ".join(_words(piece))
            if len(w) >= 3 and f" {w} " in said and (best is None or len(w) > len(best[1])):
                best = (slug, w)
    if best:
        return best
    scored = []
    for slug in films:
        key = [w for w in _words(cache.get(slug, {}).get("title") or "") if w not in TITLE_STOP]
        hits = [w for w in key if f" {w} " in said]
        if hits and (len(hits) >= 2 or len(key) == 1 or len(hits[0]) >= 6):
            scored.append((len(hits) / len(key), len(hits), slug, hits))
    scored.sort(reverse=True)
    if scored and (len(scored) == 1 or scored[0][:2] != scored[1][:2]):
        return scored[0][2], " ".join(scored[0][3])
    return None


def text_veto(m: dict, active: dict, cache: dict) -> tuple[str | None, str] | None:
    """(slug, reason) when a message vetoes one pick in words, else None.

    The pick is the one replied to (Linq reports reply_to on swipe replies,
    confirmed Nov 11). Otherwise a message that starts with "veto" counts for
    the pick it names; if it names none, slug is None and the caller asks
    which one rather than guessing (Nov 11: a guess vetoed the wrong film)."""
    text = _bare(_text(m))
    hit = VETO_TEXT_RE.match(text)
    if not hit:
        return None
    reason = text[hit.end():].strip()
    slug = active["msg_to_slug"].get(_reply_target(m) or "")
    if not slug:
        if not hit.group(1).lower().startswith("veto"):
            return None
        named = find_named_pick(reason, active["films"], cache)
        if not named:
            return None, reason
        slug, words = named
        reason = " ".join(_words(reason))  # drop the film's name from the reason
        reason = " ".join(re.sub(rf"\b{re.escape(words)}\b", "", reason).split())
    reason = re.sub(r"^(because|cause|cuz|since)\b\s*", "", reason.strip(" ,.:;-!"), flags=re.I).strip(" ,.:;-!")
    return slug, reason


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


MEDALS = (Reaction.GOLD, Reaction.SILVER, Reaction.BRONZE)
SETTLE_SECONDS = 90


def tmdb_lookup(title: str, year: int | None = None) -> dict | None:
    """tmdb.search, but a TMDB outage just means no "like X" match."""
    try:
        return tmdb.search(title, year)
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError):
        return None


def poster_lookup(tmdb_id: int) -> str | None:
    """tmdb.poster_path, but a TMDB outage just means a pick without its poster."""
    try:
        return tmdb.poster_path(tmdb_id)
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError):
        return None


def ensure_poster(entry: dict, fetch=poster_lookup) -> None:
    """Films cached before posters were stored get theirs on first use."""
    if "poster_path" not in entry and entry.get("tmdb_id"):
        entry["poster_path"] = fetch(entry["tmdb_id"])


def send_trailers(linq: Linq, chat_id: str, active: dict, cache: dict, msgs: list[dict]) -> list[str]:
    """Answer each new 👀 on a pick with its trailer, threaded under that pick. Once per film."""
    done = active.setdefault("trailers", [])
    sent = []
    for m in msgs:
        slug = active["msg_to_slug"].get(m["id"])
        if not slug or slug in done or not linq_format.wants_trailer(m):
            continue
        done.append(slug)
        url = cache.get(slug, {}).get("trailer_url")
        if url:
            mid = linq.send(chat_id, linq_format.trailer_message(url, m["id"]))
            active["msg_to_slug"][mid] = slug  # medals on the trailer card count too
        else:
            linq.say(chat_id, f"No trailer on file for {cache.get(slug, {}).get('title', slug)}, sorry.")
        sent.append(slug)
    return sent


def everyone_gave_gold(session: Session) -> bool:
    return all(Reaction.GOLD in session.state[p] for p in session.people)


def everyone_done(session: Session) -> bool:
    """Everyone has placed every medal they can (fewer films than medals is fine)."""
    need = min(len(MEDALS), len(session.films))
    return all(sum(r in session.state[p] for r in MEDALS) >= need for p in session.people)


def ready_to_tally(session: Session, active: dict, now: float) -> bool:
    """Tally once everyone has used all three medals, or once everyone has a 🥇
    and nobody has changed a reaction for SETTLE_SECONDS. People often tap 🥇
    first and the 🥈/🥉 a moment later (second live session, Nov 10)."""
    if everyone_done(session):
        return True
    sig = json.dumps({p: {r.value: f for r, f in sorted(m.items())} for p, m in session.state.items()}, sort_keys=True)
    if sig != active.get("sig"):
        active["sig"], active["sig_since"] = sig, now
        return False
    return everyone_gave_gold(session) and now - active.get("sig_since", now) >= SETTLE_SECONDS


REPLACEMENT_LABEL = "🔄 Replaces {title}: no vetoes on this one"


def handle_vetoes(linq: Linq, chat_id: str, active: dict, cache: dict, msgs: list[dict],
                  worded: list[tuple[str, str, str]], hist: History, names: dict[str, str],
                  replace, emojis, posters) -> list[str]:
    """Each new veto gets one replacement pick, chosen to avoid the reason given.

    `worded` holds (handle, slug, reason) from replies like "veto, too bleak";
    👎 reactions come with no reason. `replace(slug, reason)` returns
    (new slug, wildcard?) or None. Returns the slugs that were replaced."""
    tv = active.setdefault("text_vetoes", [])
    for handle, slug, _ in worded:
        if [handle, slug] not in tv:
            tv.append([handle, slug])
    found = [(h, s, r) for h, s, r in worded]
    for m in msgs:
        slug = active["msg_to_slug"].get(m["id"])
        if slug:
            found += [(h, slug, "") for h, r in linq_format.parse_reactions(m).votes if r is Reaction.VETO]
    handled, by = active.setdefault("vetoes_handled", []), active.setdefault("veto_by", {})
    replaced = []
    for handle, slug, reason in found:
        key = f"{handle}|{slug}"
        if key in handled:
            continue
        handled.append(key)
        who, title = names.get(handle, handle), cache.get(slug, {}).get("title", slug)
        if slug in active.get("protected", []):
            linq.say(chat_id, f"{who}, {title} is a replacement, so it can't be vetoed.")
            continue
        if handle in hist.vetoed_last_session:
            linq.say(chat_id, f"{who}, no veto tonight: you used one last time.")
            continue
        if handle in by and by[handle] != slug:
            continue  # one veto per session; the tally says which one counted
        by[handle] = slug
        got = replace(slug, reason)
        active["ask"] = (active.get("ask") or "movie night") + \
            f"\nVetoed {title}: {reason or 'no reason given'}"  # follow-ups keep avoiding it
        if not got:
            linq.say(chat_id, f"Swapping out {title}, but nothing else fits. The other picks stand.")
            continue
        new, wild = got
        label = REPLACEMENT_LABEL.format(title=title) + (" · 🃏 not on your watchlist" if wild else "")
        linq.say(chat_id, f"👎 Swapping out {title}" + (f" ({reason})" if reason else "") + ". Try this instead:")
        if wild:
            active.setdefault("entries", {})[new] = cache[new]
        ensure_poster(cache[new], posters)
        body = linq_format.pick_message(linq_format.pick_from_cache(
            cache[new], None, emojis({new: cache[new]}).get(new), label))
        active["msg_to_slug"][linq.send(chat_id, body)] = new
        active["films"].append(new)
        active.setdefault("protected", []).append(new)
        replaced.append(slug)
    return replaced


def step(linq: Linq, chat_id: str, state: State, cache: dict, history: list[dict],
         names: dict[str, str] | None = None, seed: int | None = None, now: float | None = None,
         lookup=None, taste: dict | None = None, posters=poster_lookup, emojis=emoji_mod.offline,
         ask=None) -> str | None:
    """One poll. Returns what happened, for logging. `lookup` resolves "like X" titles (tmdb.search);
    `ask` (movie_night.ask.Asker) lets Claude choose picks for asks with nuance."""
    names = names or {}
    if state.active and state.active.get("entries"):
        # Wildcards live in taste.json, which the daily rebuild may change
        # mid-session; the session keeps its own copy.
        cache = {**state.active["entries"], **cache}
    msgs = linq.messages(chat_id)
    # Chat members, not just people who have texted: someone who only ever
    # reacts still has to vote before the tally (first live session, Nov 10).
    people = linq.members(chat_id)
    new = [m for m in msgs if m["id"] not in state.seen and not (m.get("from_handle") or {}).get("is_me")]
    for m in msgs:
        if m["id"] not in state.seen:
            state.seen.append(m["id"])

    worded, consumed = [], set()
    if state.active:
        for m in new:
            tv = text_veto(m, state.active, cache)
            if tv:
                consumed.add(m["id"])
                if tv[0] is None:
                    linq.say(chat_id, "Which one? Swipe to reply on the pick you're vetoing, or name it.")
                else:
                    worded.append(((m.get("from_handle") or {}).get("handle", "?"), *tv))
    prev_ask = (state.active or {}).get("ask")
    kick, refine = None, False
    for m in reversed(new):
        if m["id"] in consumed:
            continue
        if prev_ask and _is_refinement(_text(m)):
            kick, refine = m, True
            break
        if _is_kickoff(_text(m)):
            kick = m
            break
    p = None
    if kick:
        text = f"{prev_ask}\nFollow-up: {_bare(_text(kick))}" if refine else _text(kick)
        recent = {s for h in history[-RECENT_SESSIONS_EXCLUDED:] for s in h.get("films", [])}
        p = plan(text, cache, exclude=recent, seed=seed, lookup=lookup, taste=taste, ask=ask, refine=refine)
        if not refine and not KICKOFF_RE.search(text) and (p.note or "").startswith("I couldn't find"):
            p = None  # "something like that" in passing; not a request
    if refine and not p.slugs:  # keep the picks they have rather than dropping them
        linq.say(chat_id, "Nothing from the shortlist fits that too. The picks above still stand.")
        return "refine: nothing fit"
    if p is not None and state.active is not None:
        # A fresh ask replaces a session nobody finished, instead of being
        # ignored until someone types "tally" (Nov 10: three asks went unanswered).
        state.active = None
    if state.active is None:
        if p is None:
            return None
        slugs = p.slugs
        if not slugs:
            linq.say(chat_id, "I couldn't find anything on the watchlist that fits. Try fewer limits?")
            return "kickoff: nothing fit"
        hist = history_for(history)
        no_veto = [names.get(p, p) for p in people if p in hist.vetoed_last_session]
        intro = (f"🍿 {p.note}: " if p.note else "🍿 ") + \
            f"{p.summary()}. React 🥇 🥈 🥉, 👀 for a trailer. Veto with 👎, or reply \"veto\" and why, " \
            "and I'll swap in another."
        if no_veto:
            intro += f" ({', '.join(no_veto)}: no veto tonight, you used one last time.)"
        linq.say(chat_id, intro)
        msg_to_slug = {}
        marks = emojis({s: cache[s] for s in slugs})
        for slug in slugs:
            ensure_poster(cache[slug], posters)
            label = linq_format.WILDCARD_LABEL if slug in p.wildcards else linq_format.WATCHLIST_LABEL
            body = linq_format.pick_message(
                linq_format.pick_from_cache(cache[slug], p.reasons.get(slug), marks.get(slug), label))
            msg_to_slug[linq.send(chat_id, body)] = slug
        state.active = {"kickoff_id": kick["id"], "ask": text, "films": slugs, "msg_to_slug": msg_to_slug,
                        "entries": {s: cache[s] for s in p.wildcards},
                        "started": dt.datetime.now(dt.timezone.utc).isoformat()}
        return f"kickoff: sent {len(slugs)} picks"

    trailers = send_trailers(linq, chat_id, state.active, cache, msgs)
    hist = history_for(history)
    recent = {s for h in history[-RECENT_SESSIONS_EXCLUDED:] for s in h.get("films", [])}

    def replace(slug: str, reason: str):
        active = state.active
        kept = [cache[s]["title"] for s in active["films"] if s != slug and s not in active.get("veto_by", {}).values()]
        why = reason or "no reason given, so infer what they rejected from how it differs from the picks they kept"
        text = (f"{active.get('ask') or 'movie night'}\nVetoed {cache[slug]['title']} ({why}). "
                f"Kept: {', '.join(kept)}. Choose its replacement.")
        rp = plan(text, cache, exclude=recent | set(active["films"]), seed=seed, lookup=lookup, taste=taste,
                  ask=ask, refine=True)
        new = next((s for s in rp.slugs if s not in active["films"]), None)
        return (new, new in rp.wildcards or not cache[new].get("on_watchlist")) if new else None

    swapped = handle_vetoes(linq, chat_id, state.active, cache, msgs, worded, hist, names, replace, emojis, posters)
    if swapped:
        return f"veto: replaced {', '.join(swapped)}"
    session = build_session(state.active, cache, msgs, people, hist)
    asked = any(TALLY_RE.search(_bare(_text(m))) for m in new)
    now = time.time() if now is None else now
    if not (asked or ready_to_tally(session, state.active, now)):
        return f"trailer: {', '.join(trailers)}" if trailers else None
    result = session.tally()
    linq.say(chat_id, explain(result, cache, names))
    tops = session.top_picks()
    history.append({
        "date": dt.date.today().isoformat(),
        "people": sorted(people),
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
            what = step(linq, args.chat, state, cache, history, lookup=tmdb_lookup)
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
