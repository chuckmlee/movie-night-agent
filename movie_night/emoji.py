"""One emoji per film, so a pick doesn't open with the same 🎬 as every other.

With ANTHROPIC_API_KEY, Claude picks an emoji that points at something in the
film itself (a setting, an object, a motif) from its title, overview and
keywords, once per film, cached in data/emoji.json. Without a key, or if the
call fails, a keyword or genre map stands in. Nothing here blocks a pick from
being sent.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

MODEL = "claude-opus-5-5"  # same as circle extraction; low effort, a handful of films per call
GENERIC = {"🎬", "🎥", "🍿", "🎞️", "🎞", "📽️", "📽", "🎦"}

KEYWORDS = [  # first match wins, so the specific ones come first
    ("serial killer", "🔪"), ("heist", "💰"), ("space", "🚀"), ("alien", "👽"), ("robot", "🤖"),
    ("vampire", "🧛"), ("zombie", "🧟"), ("ghost", "👻"), ("witch", "🧙"), ("shark", "🦈"),
    ("dinosaur", "🦖"), ("boxing", "🥊"), ("basketball", "🏀"), ("baseball", "⚾"), ("football", "🏈"),
    ("chess", "♟️"), ("cooking", "🍳"), ("restaurant", "🍽️"), ("wedding", "💍"), ("christmas", "🎄"),
    ("halloween", "🎃"), ("musician", "🎸"), ("jazz", "🎷"), ("dance", "💃"), ("prison", "⛓️"),
    ("journalist", "📰"), ("detective", "🔎"), ("spy", "🕵️"), ("samurai", "⚔️"), ("cowboy", "🤠"),
    ("ocean", "🌊"), ("island", "🏝️"), ("desert", "🏜️"), ("snow", "❄️"), ("new york city", "🗽"),
    ("paris, france", "🗼"), ("tokyo, japan", "🗾"), ("road trip", "🚗"), ("train", "🚂"), ("car race", "🏎️"),
    ("dog", "🐕"), ("cat", "🐈"), ("horse", "🐎"), ("hospital", "🏥"), ("school", "🏫"),
]
GENRES = {
    "Horror": "🩸", "Thriller": "🔦", "Crime": "🚨", "Mystery": "🔎", "Science Fiction": "🛸",
    "Fantasy": "🐉", "Animation": "🖍️", "Comedy": "😂", "Romance": "💘", "War": "🪖",
    "Western": "🤠", "Music": "🎶", "Documentary": "📼", "History": "📜", "Family": "🏡",
    "Adventure": "🧭", "Action": "💥", "Drama": "🎭",
}
DEFAULT = "🎞️"


def fallback(entry: dict) -> str:
    kws = [k.lower() for k in entry.get("keywords") or []]
    for word, e in KEYWORDS:
        if word in kws:
            return e
    for g in entry.get("genres") or []:
        if g in GENRES:
            return GENRES[g]
    return DEFAULT


def _ok(e: str) -> bool:
    e = (e or "").strip()
    return 0 < len(e) <= 8 and not any(c.isascii() and c.isalnum() for c in e) and e not in GENERIC


SCHEMA = {
    "type": "object",
    "properties": {"films": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "string"}, "emoji": {"type": "string"}},
        "required": ["id", "emoji"],
        "additionalProperties": False,
    }}},
    "required": ["films"],
    "additionalProperties": False,
}

PROMPT = """For each film, choose one emoji that points at something specific in it: a setting, an object,
an animal, a motif, a mood. It opens a movie suggestion in a group text, so it should make someone who
knows the film nod, and intrigue someone who doesn't.

- Not a generic cinema emoji (🎬 🎥 🍿 🎞️), and not a plain genre emoji when something more specific fits.
- Nothing that gives away a twist or an ending.
- Exactly one emoji per film.

<films>
{films}
</films>"""


def _key(slug: str, entry: dict) -> str:
    return f"tmdb-{entry['tmdb_id']}" if entry.get("tmdb_id") else slug


class Emojis:
    """Callable: {slug: entry} -> {slug: emoji}. Cached by TMDB id across sessions."""

    def __init__(self, path: Path | None = None, client=None, log=print):
        self.path, self.client, self.log = path, client, log
        try:
            self.cache = json.loads(path.read_text()) if path and path.exists() else {}
        except json.JSONDecodeError:
            self.cache = {}

    def _client(self):
        if self.client is None and os.environ.get("ANTHROPIC_API_KEY"):
            import anthropic

            # Explicit base URL: a dev shell may point ANTHROPIC_BASE_URL somewhere else.
            self.client = anthropic.Anthropic(base_url="https://api.anthropic.com", timeout=20, max_retries=1)
        return self.client

    def _ask(self, todo: dict[str, dict]) -> dict[str, str]:
        client = self._client()
        if client is None:
            return {}
        films = "\n".join(
            json.dumps({"id": k, "title": e.get("title"), "year": e.get("year"),
                        "overview": (e.get("overview") or "")[:400], "keywords": (e.get("keywords") or [])[:10]},
                       ensure_ascii=False)
            for k, e in todo.items())
        try:
            resp = client.beta.messages.create(
                model=MODEL, max_tokens=2000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
                messages=[{"role": "user", "content": PROMPT.format(films=films)}],
            )
            if resp.stop_reason != "end_turn":
                self.log(f"emoji: stopped ({resp.stop_reason})")
                return {}
            text = next((b.text for b in resp.content if b.type == "text"), "{}")
            got = {f["id"]: f["emoji"].strip() for f in json.loads(text).get("films", [])}
        except Exception as e:  # an outage just means the fallback emoji
            self.log(f"emoji: {e!r}")
            return {}
        return {k: v for k, v in got.items() if k in todo and _ok(v)}

    def __call__(self, entries: dict[str, dict]) -> dict[str, str]:
        keys = {slug: _key(slug, e) for slug, e in entries.items()}
        todo = {keys[s]: e for s, e in entries.items() if keys[s] not in self.cache}
        if todo:
            new = self._ask(todo)
            if new:
                self.cache.update(new)
                if self.path:
                    self.path.write_text(json.dumps(self.cache, indent=1, ensure_ascii=False))
        return {s: self.cache.get(keys[s]) or fallback(e) for s, e in entries.items()}


def offline(entries: dict[str, dict]) -> dict[str, str]:
    return {s: fallback(e) for s, e in entries.items()}
