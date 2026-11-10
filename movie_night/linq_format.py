"""How picks look in iMessage, and how Linq reactions map back to votes.

Both rules come from the M0 spike against the live Linq API (Nov 10, 2026):

- A trailer only gets a rich preview card when it is sent on its own, as a
  `{"type": "link"}` part with a direct watch URL. A link inside a text part
  shows no preview. So each pick is two messages: a short text, then the
  trailer link.
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


def _runtime(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def pick_text(pick: Pick) -> str:
    """The text half of a pick: title line, facts line, optional reason."""
    head = pick.title + (f" ({pick.year})" if pick.year else "")
    facts = []
    if pick.runtime_min:
        facts.append(_runtime(pick.runtime_min))
    if pick.genres:
        facts.append(", ".join(pick.genres[:2]))
    if pick.where:
        facts.append(pick.where)
    lines = [f"🎬 {head}"]
    if facts:
        lines.append(" · ".join(facts))
    if pick.reason:
        lines.append(pick.reason)
    return "\n".join(lines)


def pick_messages(pick: Pick) -> list[dict]:
    """Linq message bodies to send, in order, for one pick."""
    out = [{"message": {"parts": [{"type": "text", "value": pick_text(pick)}]}}]
    if pick.trailer_url:
        out.append({"message": {"parts": [{"type": "link", "value": pick.trailer_url}]}})
    return out


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
                else:
                    res.ignored.append((handle, emoji or "custom"))
            elif kind in TAPBACK:
                res.votes.append((handle, TAPBACK[kind]))
            else:
                res.ignored.append((handle, kind or "unknown"))
    return res
