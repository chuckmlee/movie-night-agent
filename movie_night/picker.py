"""Choose tonight's 4-5 picks from the synced watchlist.

v1 reads hints with plain keyword rules, so it is predictable and testable.
An LLM can replace `parse_hints` later without touching the rest.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

GENRE_WORDS = {
    "comedy": "Comedy", "funny": "Comedy", "laugh": "Comedy",
    "horror": "Horror", "scary": "Horror",
    "thriller": "Thriller", "suspense": "Thriller",
    "romance": "Romance", "romantic": "Romance", "romcom": "Romance",
    "sci-fi": "Science Fiction", "scifi": "Science Fiction", "science fiction": "Science Fiction",
    "animated": "Animation", "animation": "Animation", "anime": "Animation",
    "documentary": "Documentary", "doc": "Documentary",
    "action": "Action", "drama": "Drama", "crime": "Crime", "mystery": "Mystery",
    "fantasy": "Fantasy", "western": "Western", "musical": "Music", "war": "War",
}
HEAVY = {"War", "Horror"}


@dataclass
class Hints:
    max_runtime: int | None = None
    genres: set[str] = field(default_factory=set)
    avoid_genres: set[str] = field(default_factory=set)
    allow_rent: bool = False


def parse_hints(text: str) -> Hints:
    t = text.lower()
    h = Hints()
    m = re.search(r"under\s+(\d+(?:\.\d+)?)\s*(h|hr|hrs|hour|hours|m|min|mins|minutes)\b", t)
    if m:
        n, unit = float(m.group(1)), m.group(2)
        h.max_runtime = int(n * 60) if unit.startswith("h") else int(n)
    elif re.search(r"\b(short|quick|early night|not too long)\b", t):
        h.max_runtime = 110
    for word, genre in GENRE_WORDS.items():
        if re.search(rf"\b(no|not|nothing)\s+(\w+\s+)?{re.escape(word)}\b", t):
            h.avoid_genres.add(genre)
        elif re.search(rf"\b{re.escape(word)}\b", t):
            h.genres.add(genre)
    if re.search(r"\b(light|nothing heavy|not heavy|easy)\b", t):
        h.avoid_genres |= HEAVY
    if re.search(r"\b(rent|rental|renting|buy)\b", t):
        h.allow_rent = True
    h.genres -= h.avoid_genres
    return h


def eligible(entry: dict, hints: Hints) -> bool:
    if not entry.get("on_watchlist") or not entry.get("tmdb_id"):
        return False
    avail = entry.get("availability") or {}
    if not (avail.get("included") or (hints.allow_rent and avail.get("rent"))):
        return False
    rt = entry.get("runtime_min")
    if hints.max_runtime and (not rt or rt > hints.max_runtime):
        return False
    genres = set(entry.get("genres") or [])
    if genres & hints.avoid_genres:
        return False
    if hints.genres and not genres & hints.genres:
        return False
    return True


def choose(cache: dict, hints: Hints, n: int = 5, exclude: set[str] = frozenset(), seed: int | None = None) -> list[str]:
    """Return up to n slugs: well rated, varied in genre, and not repeated from recent sessions.

    Ranking is the Letterboxd rating plus a little randomness, so the same
    top-rated films don't come back every night. At most two picks share a
    first genre.
    """
    rng = random.Random(seed)
    pool = [(slug, e) for slug, e in cache.items() if slug not in exclude and eligible(e, hints)]
    scored = sorted(pool, key=lambda se: (se[1].get("letterboxd_rating") or 3.0) + rng.uniform(0, 0.6), reverse=True)
    picks, per_genre = [], {}
    for slug, e in scored:
        g = (e.get("genres") or ["?"])[0]
        if per_genre.get(g, 0) >= 2:
            continue
        picks.append(slug)
        per_genre[g] = per_genre.get(g, 0) + 1
        if len(picks) == n:
            break
    return picks
