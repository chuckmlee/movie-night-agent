"""How picks look in iMessage, and how Linq reactions map back to votes.

Both rules come from the M0 spike against the live Linq API (Nov 10, 2026):

- A trailer only gets a rich preview card when it is sent on its own, as a
  `{"type": "link"}` part with a direct watch URL. A link inside a text part
  shows no preview.
- Media and text parts can share one message, so each pick is one message:
  the TMDB poster, then the short text. Trailers are sent on request: react
  👀 on a pick and Delo replies to it, in thread, with the trailer card
  (Chuck, Nov 10: "instead of just dumping the trailer").
- Reactions show up on a message part as `type: "custom"` with `custom_emoji`
  set (🥇), or as a standard tapback type such as `dislike` (👎).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .rules import Reaction


@dataclass(frozen=True)
class Pick:
    title: str
    year: int | None = None
    runtime_min: int | None = None
    genres: tuple[str, ...] = ()
    where: str | None = None  # e.g. "Netflix" or "Rent on Prime Video"
    reason: str | None = None  # one line on why it fits tonight
    trailer_url: str | None = None  # direct watch URL, not a search page
    poster_url: str | None = None  # TMDB image URL
    emoji: str = "🎬"  # one per film, from movie_night.emoji
    label: str | None = None  # only for wildcards and replacements, in italics at the end
    score: str | None = None  # "86/100 · critics' favorite" (movie_night.quality.line)


POSTER_BASE = "https://image.tmdb.org/t/p/w500"
TRAILER_EMOJI = "👀"
SEEN_EMOJI = "🙈"  # "seen it": never offer this film again (Nov 11)


def poster_url(entry: dict) -> str | None:
    path = entry.get("poster_path")
    return f"{POSTER_BASE}{path}" if path else None


WILDCARD_LABEL = "🃏 Wildcard: not on your watchlist"


def pick_from_cache(entry: dict, reason: str | None = None, emoji: str | None = None,
                    label: str | None = None) -> Pick:
    """Build a Pick from a data/films.json entry written by movie_night.sync."""
    from .tmdb import Availability

    from .quality import line

    where = Availability(**entry["availability"]).where() if entry.get("availability") else None
    if where and where.startswith("On "):
        where = "Streaming on " + where[3:]
    from .honors import line as honors_line

    from .festivals import line as festival_line

    for h in (honors_line(entry), festival_line(entry)):
        if h and h not in (reason or ""):
            reason = f"{reason}\n{h}" if reason else h
    quoted = any(x.startswith("💬") for x in (reason or "").splitlines())
    return Pick(entry["title"], entry.get("year"), entry.get("runtime_min"),
                tuple(entry.get("genres") or ()), where, reason, entry.get("trailer_url"), poster_url(entry),
                emoji or "🎬", label, line(entry, skip_circle=quoted))


def _runtime(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def _u16(text: str) -> int:
    """Linq ranges count UTF-16 code units, so an emoji can count as 2."""
    return len(text.encode("utf-16-le")) // 2


def pick_part(pick: Pick) -> dict:
    """The text part of a pick (layout agreed with Chuck, Nov 11):

        🦉 Twin Peaks: Fire Walk with Me (1992)     title bold
        86/100 · critics' favorite
        2h 15m · Drama, Mystery

        Streaming on Max

        Why it fits, in one sentence.
        💬 ann (5★): “Pure dread.”                  quote italic

        🃏 Wildcard: not on your watchlist          wildcards only, italic
    """
    head = f"{pick.emoji} "
    facts = []
    if pick.runtime_min:
        facts.append(_runtime(pick.runtime_min))
    if pick.genres:
        facts.append(", ".join(pick.genres[:2]))
    blocks = [[head + pick.title + (f" ({pick.year})" if pick.year else "")]
              + ([pick.score] if pick.score else []) + ([" · ".join(facts)] if facts else [])]
    if pick.where:
        blocks.append([pick.where])
    why = [x.strip() for x in (pick.reason or "").splitlines() if x.strip()]
    if why:
        blocks.append(why)
    if pick.label:
        blocks.append([pick.label])
    text, decorations = "", [{"range": [_u16(head), _u16(head) + _u16(pick.title)], "style": "bold"}]
    for i, block in enumerate(blocks):
        for j, ln in enumerate(block):
            if i or j:
                text += "\n\n" if j == 0 else "\n"
            if ln.startswith("💬") or ln == pick.label:
                decorations.append({"range": [_u16(text), _u16(text) + _u16(ln)], "style": "italic"})
            text += ln
    return {"type": "text", "value": text, "text_decorations": decorations}


def pick_text(pick: Pick) -> str:
    return pick_part(pick)["value"]


def pick_message(pick: Pick) -> dict:
    """The Linq message body for one pick: poster (when there is one), then the text."""
    parts = [{"type": "media", "url": pick.poster_url}] if pick.poster_url else []
    parts.append(pick_part(pick))
    return {"message": {"parts": parts}}


def trailer_message(url: str, reply_to: str) -> dict:
    """The trailer card, threaded under the pick it belongs to. A link part has to be alone."""
    return {"message": {"parts": [{"type": "link", "value": url}], "reply_to": {"message_id": reply_to}}}


def wants_trailer(message: dict) -> bool:
    """Someone other than Delo reacted 👀 on this message."""
    return any(r.get("type") == "custom" and r.get("custom_emoji") == TRAILER_EMOJI and not r.get("is_me")
               for part in message.get("parts") or [] for r in part.get("reactions") or [])


def seen_by(message: dict) -> list[str]:
    """Handles of people (not Delo) who reacted 🙈 on this message."""
    return [(r.get("handle") or {}).get("handle", "?") for part in message.get("parts") or []
            for r in part.get("reactions") or []
            if r.get("type") == "custom" and r.get("custom_emoji") == SEEN_EMOJI and not r.get("is_me")]


CUSTOM = {"🥇": Reaction.GOLD, "🥈": Reaction.SILVER, "🥉": Reaction.BRONZE, "🚫": Reaction.VETO}
TAPBACK = {"dislike": Reaction.VETO}  # 👎; confirmed live on Nov 10


@dataclass
class ParsedReactions:
    votes: list[tuple[str, Reaction]] = field(default_factory=list)  # (handle, reaction)
    ignored: list[tuple[str, str]] = field(default_factory=list)  # (handle, what they sent)


def parse_reactions(message: dict) -> ParsedReactions:
    """Read every reaction on a Linq message (as returned by GET /chats/{id}/messages)."""
    res = ParsedReactions()
    for part in message.get("parts") or []:
        for r in part.get("reactions") or []:
            if r.get("is_me"):
                continue
            handle = (r.get("handle") or {}).get("handle", "?")
            kind = r.get("type")
            if kind == "custom":
                emoji = r.get("custom_emoji") or ""
                if emoji in CUSTOM:
                    res.votes.append((handle, CUSTOM[emoji]))
                elif emoji in (TRAILER_EMOJI, SEEN_EMOJI):
                    continue  # a request, not a vote
                else:
                    res.ignored.append((handle, emoji or "custom"))
            elif kind in TAPBACK:
                res.votes.append((handle, TAPBACK[kind]))
            else:
                res.ignored.append((handle, kind or "unknown"))
    return res
