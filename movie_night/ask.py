"""Nuanced asks: "something like The Devils but less shocking, as intellectually rich".

The keyword matcher in search.py can find films like The Devils, but it can't
weigh "less shocking". For an ask with that kind of texture, Claude reads it
together with a shortlist of real candidates (watchlist films and wildcards,
each with its synopsis and TMDB tags) and chooses up to five, each with one
line on why it fits. Claude only ranks and explains: the candidates, the
streaming filters and the 3 + 2 labels all come from code, and an id outside
the shortlist is dropped.

Plain asks ("movie night?", "spy movies", "like Heat") never reach this, and
without ANTHROPIC_API_KEY, or if the call fails, the keyword matcher answers.
"""

from __future__ import annotations

import json
import os
import re

MODEL = "claude-opus-5-5"
POOL = 50  # candidates shown to Claude
PICKS = 5

# Words that make an ask more than a topic: comparisons, tone, exceptions.
NUANCE_RE = re.compile(
    r"\b(but|less|more|without|not too|not as|as \w+ as|though|yet|except|instead|rather|vibe|mood|feel|"
    r"smart|intellectual\w*|cerebral|cozy|light|dark|weird|slow|tense|gentle|funny|sad|uplifting|bleak|"
    r"rich|deep|thoughtful|fun|scary|creepy|romantic|quiet|wild|strange|beautiful|unsettling)\b", re.I)
KICK_WORDS = re.compile(r"\b(hey|ok|delo|movie|movies|film|films|night|tonight|time|pick|us|a|something|anything|"
                        r"some|any|for|we|want|to|watch|please|ideas?|like|similar|what|should)\b", re.I)


def is_nuanced(text: str) -> bool:
    """True when the ask says how a film should feel, not just what it's about."""
    rest = KICK_WORDS.sub(" ", text)
    words = re.findall(r"[a-z']{3,}", rest.lower())
    return bool(NUANCE_RE.search(text)) and len(words) >= 2


SCHEMA = {
    "type": "object",
    "properties": {
        "note": {"type": "string", "description": "the ask restated in at most 8 words, for the intro line"},
        "picks": {"type": "array", "items": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "why": {"type": "string"}},
            "required": ["id", "why"],
            "additionalProperties": False,
        }},
    },
    "required": ["note", "picks"],
    "additionalProperties": False,
}

PROMPT = """A couple is choosing a movie for tonight and asked their group-text assistant:

<ask>{ask}</ask>
{seed}
Here are the films they could watch: their own watchlist, plus a few wildcards they haven't seen.

<candidates>
{candidates}
</candidates>

Choose the {n} candidates that best answer the ask, best first. Read the ask closely: if it says
"like X but less Y", a film that is just like X with even more Y is a bad pick. If it has
follow-ups, they narrow or change the first ask, and the latest wins where they conflict. Prefer watchlist
films when two fit about equally. Use only ids from the list.

For each pick write `why`: one short line (at most 15 words) on how it answers the ask, in plain
words a friend would use. Ground it in the synopsis, tags and credits given; don't claim things they don't
support, and don't give away twists or endings.

Also write `note`: the whole ask, follow-ups included, restated in at most 8 words, like "Like The Devils, less shocking"."""


def _line(slug: str, e: dict) -> str:
    return json.dumps({
        "id": slug,
        "title": e.get("title"), "year": e.get("year"),
        "list": "watchlist" if e.get("on_watchlist") else "wildcard",
        "runtime": e.get("runtime_min"), "genres": (e.get("genres") or [])[:3],
        "director": e.get("directors") or None, "cast": (e.get("cast") or [])[:3] or None,
        "country": (e.get("countries") or [])[:2] or None, "language": e.get("language"),
        "tags": [k for k in (e.get("keywords") or [])][:12],
        "synopsis": (e.get("overview") or "")[:350],
    }, ensure_ascii=False)


class Asker:
    """Callable: (ask, {slug: entry}, seed film or None) -> (note, [(slug, why)]) or None."""

    def __init__(self, client=None, log=print):
        self.client, self.log = client, log

    def _client(self):
        if self.client is None and os.environ.get("ANTHROPIC_API_KEY"):
            import anthropic

            # Explicit base URL: a dev shell may point ANTHROPIC_BASE_URL somewhere else.
            self.client = anthropic.Anthropic(base_url="https://api.anthropic.com", timeout=60, max_retries=1)
        return self.client

    def __call__(self, ask: str, pool: dict[str, dict], seed: dict | None = None):
        client = self._client()
        if client is None or not pool:
            return None
        seed_block = ""
        if seed:
            seed_block = ("\nThe film they named, for reference:\n<named>" + json.dumps({
                "title": seed.get("title"), "year": seed.get("year"), "genres": seed.get("genres"),
                "director": seed.get("directors"), "cast": (seed.get("cast") or [])[:3],
                "tags": (seed.get("keywords") or [])[:15], "synopsis": (seed.get("overview") or "")[:500],
            }, ensure_ascii=False) + "</named>\n")
        prompt = PROMPT.format(ask=ask, seed=seed_block, n=min(PICKS, len(pool)),
                               candidates="\n".join(_line(s, e) for s, e in pool.items()))
        try:
            resp = client.beta.messages.create(
                model=MODEL, max_tokens=4000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
                messages=[{"role": "user", "content": prompt}],
            )
            if resp.stop_reason != "end_turn":
                self.log(f"ask: stopped ({resp.stop_reason})")
                return None
            out = json.loads(next((b.text for b in resp.content if b.type == "text"), "{}"))
        except Exception as e:  # an outage just means the keyword matcher answers
            self.log(f"ask: {e!r}")
            return None
        picks = []
        for p in out.get("picks", []):
            if p.get("id") in pool and p["id"] not in [s for s, _ in picks]:
                picks.append((p["id"], (p.get("why") or "").strip()))
        if not picks:
            return None
        return (out.get("note") or "").strip() or None, picks[:PICKS]
