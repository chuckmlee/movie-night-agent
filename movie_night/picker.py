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


def eligible(entry: dict, hints: Hints, wildcard: bool = False) -> bool:
    """Wildcards may be rentals: they're labeled, and there are only two."""
    if not entry.get("tmdb_id") or bool(entry.get("on_watchlist")) == wildcard:
        return False
    avail = entry.get("availability") or {}
    if not (avail.get("included") or ((hints.allow_rent or wildcard) and avail.get("rent"))):
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


TASTE_JITTER = 5.0  # taste scores run 0 to ~17; this keeps the top 30 or so in rotation
TASTE_SCALE = 17.0
FIT_SHARE = 0.6  # ranking = 60% fit (taste) + 40% consensus quality (movie_night.quality), when known


def with_quality(fit: float, e: dict, scale: float = TASTE_SCALE) -> float:
    """Blend a fit score (0..scale) with the film's 0-100 quality score, if it has one."""
    q = e.get("quality")
    return fit if q is None else FIT_SHARE * fit + (1 - FIT_SHARE) * q * scale / 100


def choose(cache: dict, hints: Hints, n: int = 5, exclude: set[str] = frozenset(), seed: int | None = None,
           taste: dict | None = None, wildcard: bool = False) -> list[str]:
    """Return up to n slugs: a good fit, varied in genre, and not repeated from recent sessions.

    With a taste profile, ranking is its score plus some randomness, so the
    same best fits don't come back every night. Without one, it's the
    Letterboxd rating. At most two picks share a first genre.
    """
    rng = random.Random(seed)
    pool = [(slug, e) for slug, e in cache.items() if slug not in exclude and eligible(e, hints, wildcard)]

    def key(se):
        slug, e = se
        if wildcard:
            return with_quality(e.get("score", 0), e) + rng.uniform(0, TASTE_JITTER)
        if taste and slug in taste:
            return with_quality(taste[slug][0], e) + rng.uniform(0, TASTE_JITTER)
        return with_quality(e.get("letterboxd_rating") or 3.0, e, 5.0) + rng.uniform(0, 0.6)

    scored = sorted(pool, key=key, reverse=True)
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


WILDCARDS = 2


@dataclass
class Plan:
    slugs: list[str]
    reasons: dict[str, str]
    note: str | None = None  # one line for the intro, e.g. "Spy films" or "Like The Wicker Man (1973)"
    wildcards: list[str] = field(default_factory=list)  # slugs in `slugs` that are off the watchlist
    labels: dict[str, str] = field(default_factory=dict)  # slug -> italic last line ("💎 Hidden gem: ...")
    kinds: dict[str, str] = field(default_factory=dict)  # slug -> "new" | "twin" | "gem" | "watchlist" (mix only)
    extra: str | None = None  # one more intro line, e.g. what's coming to rent soon

    def summary(self) -> str:
        if self.kinds:
            counts = {k: sum(1 for v in self.kinds.values() if v == k) for k in KIND_NAMES}
            bits = [KIND_NAMES[k](c) for k, c in counts.items() if c]
            return f"{len(self.slugs)} picks: " + (", ".join(bits[:-1]) + " and " + bits[-1] if len(bits) > 1 else bits[0])
        n_list = len(self.slugs) - len(self.wildcards)
        s = f"{n_list} picks from the watchlist"
        if self.wildcards:
            s += f" and {len(self.wildcards)} wildcard{'s' if len(self.wildcards) > 1 else ''} 🃏"
        return s


KIND_NAMES = {
    "new": lambda c: f"{c} new on your services 🆕",
    "twin": lambda c: f"{c} from {'a taste twin' if c == 1 else 'taste twins'} 👯",
    "gem": lambda c: f"{c} hidden gem{'s' if c > 1 else ''} 💎",
    "watchlist": lambda c: f"{c} from the watchlist",
    "wild": lambda c: f"{c} wildcard{'s' if c > 1 else ''} 🃏",
}
NEW_SLOTS, TWIN_SLOTS, GEM_SLOTS = 2, 1, 2
WILD_SUFFIX = " · 🃏 not on your watchlist"


def twin_label(e: dict) -> str:
    t = max(e.get("twins") or [{}], key=lambda t: t.get("weight", 0))
    who = t.get("who", "someone you follow")
    both = (t.get("both_loved") or [None])[0]
    return f"👯 {who} rates like you" + (f": you both loved {both}" if both else "")


def mix(cache: dict, h: Hints, n: int, exclude: set[str], seed: int | None, scores: dict) -> Plan:
    """Tonight's mix (Chuck, Nov 11): watchlist films that just started streaming, a film
    a taste twin loved (or another circle wildcard), hidden gems (loved, little seen), then the watchlist by taste."""
    from . import discover

    rng = random.Random(seed)

    def fit(slug, e):
        if not e.get("on_watchlist"):
            return with_quality(e.get("score", 0), e) + rng.uniform(0, TASTE_JITTER)
        if slug in scores:
            return with_quality(scores[slug][0], e) + rng.uniform(0, TASTE_JITTER)
        return with_quality((e.get("letterboxd_rating") or 3.0) * TASTE_SCALE / 5, e) + rng.uniform(0, TASTE_JITTER)

    pool = [(s, e) for s, e in cache.items() if s not in exclude and (eligible(e, h) or eligible(e, h, wildcard=True))]
    ranked = sorted(pool, key=lambda se: fit(*se), reverse=True)
    picks, kinds, labels, per_genre = [], {}, {}, {}

    def take(cands, kind, limit, label=None):
        got = 0
        for slug, e in cands:
            if got >= limit or len(picks) >= n:
                break
            g = (e.get("genres") or ["?"])[0]
            if slug in kinds or per_genre.get(g, 0) >= 2:
                continue
            picks.append(slug)
            kinds[slug] = kind
            per_genre[g] = per_genre.get(g, 0) + 1
            lab = label(e) if label else None
            if not e.get("on_watchlist"):
                lab = (lab or "🃏 Wildcard") + (WILD_SUFFIX if lab else ": not on your watchlist")
            if lab:
                labels[slug] = lab
            got += 1

    take([se for se in ranked if se[1].get("new_on") and se[1].get("on_watchlist")], "new", NEW_SLOTS,
         lambda e: f"🆕 New on {e['new_on']['on']} since {discover.short_date(e['new_on']['since'])}")
    take([se for se in ranked if se[1].get("twins") and not se[1].get("on_watchlist")], "twin", TWIN_SLOTS, twin_label)
    if "twin" not in kinds.values():  # no taste twin has loved anything new yet: a circle wildcard instead
        take([se for se in ranked if not se[1].get("on_watchlist")], "wild", 1)
    take([se for se in ranked if discover.gem(se[1]) is not None], "gem", GEM_SLOTS,
         lambda e: "💎 Hidden gem: loved, little seen")
    take([se for se in ranked if se[1].get("on_watchlist")], "watchlist", n)
    order = ["new", "twin", "gem", "watchlist", "wild"]  # a plain wildcard goes last, as before
    picks.sort(key=lambda s: order.index(kinds[s]))
    reasons = {}
    for s in picks:
        e = cache[s]
        line = ((scores.get(s) or [None, ""])[1] or "").strip() if e.get("on_watchlist") else (e.get("reason") or "")
        if line:
            reasons[s] = line
    return Plan(picks, reasons, wildcards=[s for s in picks if not cache[s].get("on_watchlist")],
                labels=labels, kinds=kinds)


def ask_pool(cache: dict, h: Hints, exclude: set[str], scores: dict, seed_film: dict | None,
             vocab, size: int = 50) -> dict[str, dict]:
    """The shortlist Claude chooses from for a nuanced ask: the closest matches to a
    named film first (if any), then the household's best-scored films; mostly watchlist."""
    from . import search

    n_films = sum(1 for e in cache.values() if e.get("on_watchlist"))

    def ranked(wildcard: bool) -> list[str]:
        rows = []
        for slug, e in cache.items():
            if slug in exclude or not eligible(e, h, wildcard=wildcard):
                continue
            if seed_film and e.get("tmdb_id") == seed_film.get("tmdb_id"):
                continue
            sim = search.similarity(e, seed_film, vocab, n_films)[0] if seed_film else 0.0
            fit = e.get("score") if wildcard else (scores.get(slug) or [None])[0]
            rows.append((sim, fit if fit is not None else (e.get("letterboxd_rating") or 0), slug))
        rows.sort(reverse=True)
        return [r[2] for r in rows]

    wild_n = size // 5
    picks = ranked(False)[:size - wild_n] + ranked(True)[:wild_n]
    return {s: cache[s] for s in picks}


def plan(text: str, cache: dict, exclude: set[str] = frozenset(), seed: int | None = None,
         lookup=None, n: int = 5, taste: dict | None = None, ask=None, refine: bool = False) -> Plan:
    """Turn a kickoff message into picks: plain, topic search, or "more like X".

    `lookup(title, year)` resolves a title on TMDB (tmdb.search); injected so
    tests don't hit the network. `taste` is data/taste.json (movie_night.taste):
    watchlist scores and reasons, plus wildcards, which `cache` must already
    include as entries with "wildcard": true. `refine` marks a follow-up
    ("limit to Catholic themes") folded into the last ask; it goes to Claude
    even without a tone word.
    """
    scores = (taste or {}).get("scores") or {}
    from . import search

    hints = parse_hints(text)
    vocab = search.vocabulary(cache)
    like = search.find_like(text)
    seed_film = lookup(*like) if (like and lookup) else None
    topics = {} if seed_film else search.find_topics(text, vocab)
    wanted, avoided = search.find_people(text, cache)
    if avoided:  # "no David Lynch tonight"
        exclude = set(exclude) | {s for s, e in cache.items()
                                  if set(avoided) & set((e.get("directors") or []) + (e.get("cast") or []))}
    if wanted:  # a name isn't a topic: "lynch" shouldn't also match keywords
        topics = {k: v for k, v in topics.items() if not any(k in w.lower() for w in wanted)}

    if ask is not None:
        from .ask import is_nuanced

        if refine or is_nuanced(text):
            got = ask(text, ask_pool(cache, hints, exclude, scores, seed_film, vocab), seed_film)
            if got:
                note, chosen = got
                reasons = {s: why for s, why in chosen if why}
                slugs = [s for s, _ in chosen]
                return Plan(slugs, reasons, note, wildcards=[s for s in slugs if not cache[s].get("on_watchlist")])

    def run(h: Hints) -> Plan:
        if seed_film:
            n_films = sum(1 for e in cache.values() if e.get("on_watchlist"))
            scored = []
            for slug, e in cache.items():
                if slug in exclude or not eligible(e, h) or e.get("tmdb_id") == seed_film["tmdb_id"]:
                    continue
                score, shared = search.similarity(e, seed_film, vocab, n_films)
                if score > 0:
                    included = bool((e.get("availability") or {}).get("included"))
                    scored.append((included, score, e.get("letterboxd_rating") or 0, slug, shared))
            scored.sort(reverse=True)
            top = scored[:n]
            reasons = {}
            for _, _, _, slug, shared in top:
                bits = [k for k in shared[:3]]
                if bits:
                    reasons[slug] = "Shares " + ", ".join(bits) + f" with {seed_film['title']}"
            label = seed_film["title"] + (f" ({seed_film['year']})" if seed_film.get("year") else "")
            return Plan([t[3] for t in top], reasons, f"More like {label}")
        if wanted and not seed_film:
            rng = random.Random(seed)
            hits = []
            for slug, e in cache.items():
                if slug in exclude or not eligible(e, h):
                    continue
                credits = search.credits_for(e, wanted)
                if credits:
                    included = bool((e.get("availability") or {}).get("included"))
                    fit = with_quality(scores[slug][0], e) if slug in scores else \
                        with_quality(e.get("letterboxd_rating") or 3.0, e, 5.0)
                    on_topic = bool(search.matches_topics(e, topics)) if topics else True
                    hits.append((included, on_topic, len(credits), fit + rng.uniform(0, 1), slug, credits))
            hits.sort(reverse=True)
            top = hits[:n]
            return Plan([t[4] for t in top], {t[4]: ", ".join(t[5]) for t in top}, " / ".join(wanted))
        if topics:
            rng = random.Random(seed)
            hits = []
            for slug, e in cache.items():
                if slug in exclude or not eligible(e, h):
                    continue
                matched = search.matches_topics(e, topics)
                if matched:
                    included = bool((e.get("availability") or {}).get("included"))
                    fit = with_quality(scores[slug][0], e) + rng.uniform(0, TASTE_JITTER) if slug in scores else \
                        with_quality(e.get("letterboxd_rating") or 3.0, e, 5.0) + rng.uniform(0, 0.6)
                    hits.append((included, len(matched), fit, slug, matched))
            hits.sort(reverse=True)
            top = hits[:n]
            reasons = {t[3]: ", ".join(t[4]).capitalize() for t in top}
            return Plan([t[3] for t in top], reasons, " / ".join(t.capitalize() for t in topics))
        if taste:
            from . import discover

            m = mix(cache, h, n, exclude, seed, scores)
            m.extra = discover.soon_line(cache, taste)
            return m
        wild = []
        slugs = choose(cache, h, n=n - len(wild), exclude=exclude, seed=seed, taste=scores)
        reasons = {}
        for s in slugs:
            line = ((scores.get(s) or [None, ""])[1] or "").strip()
            if line:
                reasons[s] = line
        for s in wild:
            if cache[s].get("reason"):  # the 🃏 label goes on the pick message itself
                reasons[s] = cache[s]["reason"]
        return Plan(slugs + wild, reasons, wildcards=wild)

    result = run(hints)
    if len(result.slugs) < 3 and not hints.allow_rent:
        hints.allow_rent = True
        wider = run(hints)
        if len(wider.slugs) > len(result.slugs):
            result = wider
    if like and not seed_film:
        result.note = f"I couldn't find “{like[0]}” on TMDB, so here are regular picks"
    return result
