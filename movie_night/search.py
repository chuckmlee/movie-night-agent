"""Search and "more like this" over the synced watchlist, using TMDB keywords.

- Topic search: "we want to watch some spy movies" matches films whose TMDB
  keywords include "spy" (or a synonym like "espionage"). Genres stay in
  picker.parse_hints; topics are everything TMDB tags below the genre level.
- More like this: "something a lot like The Wicker Man" looks the title up on
  TMDB and ranks the watchlist by shared keywords (rarer keywords count more),
  shared genres, and whether TMDB lists the film as related.

No LLM: matching is against the watchlist's own keyword vocabulary, so a word
only counts as a topic if some film on the list is tagged with it.
"""

from __future__ import annotations

import math
import re
from collections import Counter

# Extra words people say for a TMDB keyword.
SYNONYMS = {
    "spy": ["spy", "espionage", "secret agent", "mi6", "double agent", "spy thriller"],
    "heist": ["heist", "bank robbery", "robbery"],
    "noir": ["film noir", "neo-noir"],
    "zombie": ["zombie", "zombie apocalypse"],
    "vampire": ["vampire"],
    "witch": ["witch", "witchcraft"],
    "cult": ["cult", "religious cult"],
    "folk": ["folk horror"],
    "christmas": ["christmas", "christmas party", "christmas eve"],
    "space": ["space", "outer space", "space travel", "astronaut"],
    "alien": ["alien", "alien invasion", "extraterrestrial"],
    "time travel": ["time travel"],
    "samurai": ["samurai"],
    "gangster": ["gangster", "mafia", "organized crime"],
    "mafia": ["mafia", "organized crime"],
    "courtroom": ["courtroom", "trial", "lawyer"],
    "boxing": ["boxing", "boxer"],
    "sports": ["sports", "basketball", "baseball", "football (soccer)", "boxing"],
    "road trip": ["road trip", "road movie"],
    "revenge": ["revenge"],
    "serial killer": ["serial killer"],
    "conspiracy": ["conspiracy", "political conspiracy"],
    "dystopia": ["dystopia", "dystopian"],
    "post-apocalyptic": ["post-apocalyptic future", "post-apocalyptic"],
    "anime": ["anime"],
    "cooking": ["cooking", "chef", "food", "restaurant"],
}
STOP = set("""a an the and or but if of to in on at for with without from by about some any something anything
we us our i me my you your he she they them it its this that these those is are was were be been am
want wanna watch watching see seeing tonight today night movie movies film films flick pick picks show
delo please can could would should will lets let's like similar vein kind sort type more less lot very really
just maybe also good great fun new old one two what what's whats how who which""".split())

LIKE_RE = re.compile(
    r"\b(?:(?:a lot|much|kind of|sort of|something|anything|more|movies?|films?)\s+)?"
    r"(?:like|similar to|as good as|in the vein of|along the lines of)\s+"
    r"[\"“']?(?P<title>[^\"”'?!.,]+?)[\"”']?\s*(?:\((?P<year>\d{4})\))?\s*(?:[?!.,]|$)",
    re.I,
)
# Tags too generic or tonal to say two films are alike.
GENERIC = {"based on novel or book", "woman director", "based on true story", "black and white", "duringcreditsstinger",
           "aftercreditsstinger", "remake", "sequel", "psychotronic", "bold", "intense", "ambiguous", "awestruck",
           "vibrant", "admiring", "suspenseful", "dramatic", "melancholy", "provocative", "cautionary", "song",
           "new york city", "los angeles, california", "london, england", "paris, france", "1970s", "1980s"}
NOT_TITLES = {"that", "this", "it", "those", "these", "last time", "before", "usual", "always"}


def find_like(text: str) -> tuple[str, int | None] | None:
    """The title in "something like X", or None."""
    for m in LIKE_RE.finditer(text):
        title = m.group("title").strip()
        title = re.sub(r"^(?:the movie|the film)\s+", "", title, flags=re.I)
        # "like The Devils but less shocking": the title ends where the qualifier starts.
        title = re.split(r"\s+(?:but|though|yet|except|only|minus|without|less)\b", title, flags=re.I)[0]
        if re.search(r"\b(?:like|similar to)\b", title, re.I):  # "like something like X"
            return find_like(title + (f" ({m.group('year')})" if m.group("year") else ""))
        if title.lower() in NOT_TITLES or len(title) < 2:
            continue
        return title, int(m.group("year")) if m.group("year") else None
    return None


def vocabulary(cache: dict) -> Counter:
    """How many watchlist films carry each keyword (for rarity weights)."""
    return Counter(k for e in cache.values() if e.get("on_watchlist") for k in set(e.get("keywords") or []))


def find_topics(text: str, vocab: Counter) -> dict[str, list[str]]:
    """Map each topic the person named to the TMDB keywords it stands for.

    A topic is a word or two-word phrase from the message that is a known
    synonym or a keyword some watchlist film actually has.
    """
    t = text.lower()
    like = find_like(text)
    if like:  # don't read the title in "like X" as topics
        t = t.replace(like[0].lower(), " ")
    words = re.findall(r"[a-z][a-z'-]*", t)
    words = [w[:-1] if w.endswith("s") and w[:-1] in vocab | dict.fromkeys(SYNONYMS) else w for w in words]
    grams = [" ".join(words[i:i + 2]) for i in range(len(words) - 1)] + words
    topics: dict[str, list[str]] = {}
    for g in grams:
        if g in STOP or any(part in STOP for part in g.split()) and " " not in g:
            continue
        if any(g in other and g != other for other in topics):
            continue
        if g in SYNONYMS:
            topics[g] = SYNONYMS[g]
        elif vocab.get(g, 0) >= 2:  # a real tag on the list, not a one-off
            topics[g] = [g]
    return topics


NEGATE_RE = r"\b(?:no|not|without|nothing\s+(?:by|from|with)|skip|except)\s+(?:\w+\s+){0,2}$"


def people_index(cache: dict) -> dict[str, str]:
    """Lowercase name -> full name, for every director and top-billed actor in the cache,
    plus surnames that belong to only one of them ("lynch" -> "David Lynch")."""
    full, by_last = {}, {}
    for e in cache.values():
        for name in (e.get("directors") or []) + (e.get("cast") or []):
            full[name.lower()] = name
            last = name.split()[-1].lower()
            if len(last) >= 4 and last not in STOP:
                by_last.setdefault(last, set()).add(name)
    index = dict(full)
    for last, names in by_last.items():
        if len(names) == 1:
            index.setdefault(last, next(iter(names)))
    return index


def find_people(text: str, cache: dict) -> tuple[list[str], list[str]]:
    """Directors and actors the ask names: (wanted, avoided). "Lynch movies" wants David Lynch;
    "no David Lynch tonight" avoids him. Full names win over a bare surname."""
    t = " " + " ".join(re.findall(r"[a-z0-9'\-]+", text.lower())) + " "
    wanted, avoided, taken = [], [], []
    for key, name in sorted(people_index(cache).items(), key=lambda kv: -len(kv[0])):
        m = re.search(rf"(?<=\s){re.escape(key)}(?:'s)?(?=\s)", t)
        if not m or name in wanted + avoided or any(m.start() >= a and m.end() <= b for a, b in taken):
            continue
        taken.append((m.start(), m.end()))
        (avoided if re.search(NEGATE_RE, t[:m.start()]) else wanted).append(name)
    return wanted, avoided


def credits_for(entry: dict, names: list[str]) -> list[str]:
    """How the film relates to the named people: ["Directed by David Lynch", "With Laura Dern"]."""
    out = [f"Directed by {n}" for n in names if n in (entry.get("directors") or [])]
    return out + [f"With {n}" for n in names if n in (entry.get("cast") or [])]


def matches_topics(entry: dict, topics: dict[str, list[str]]) -> list[str]:
    """Which of the requested topics this film matches. Any one is enough
    ("heist or noir"); films matching more of them rank higher."""
    kws = set(entry.get("keywords") or [])
    return [topic for topic, keys in topics.items() if kws & set(keys)]


def similarity(entry: dict, seed: dict, vocab: Counter, n_films: int) -> tuple[float, list[str]]:
    """Score a watchlist film against the "like X" film; also return the shared keywords, rarest first."""
    seed_kw = set(seed.get("keywords") or []) - GENERIC
    shared = seed_kw & set(entry.get("keywords") or [])
    related = entry.get("tmdb_id") in set(seed.get("related_ids") or [])
    if not shared and not related:
        return 0.0, []
    idf = {k: math.log((n_films + 1) / (vocab.get(k, 0) + 1)) for k in shared}
    score = sum(idf.values())
    score += 0.75 * len(set(seed.get("genres") or []) & set(entry.get("genres") or []))
    if related:
        score += 3.0
    return score, sorted(shared, key=lambda k: -idf[k])
