"""Household taste profile: what the shared Letterboxd account loves.

    python3 -m movie_night.taste chucklee --report data/taste-report.md

- Reads films with their star rating and heart: the newest 72 from /<user>/films/
  (later pages are bot-blocked) plus, when given, Letterboxd's data export. The
  account is shared and its ratings are a joint verdict, so this is one
  household profile, not two.
- Looks up each film once (Letterboxd page for the TMDB id, then TMDB for
  keywords, genres and recommendations) and caches it in data/rated.json.
- Scores films by how much their TMDB keywords and genres overlap what the
  household rated highly, minus what it rated low, plus a boost when TMDB
  recommends them from a film the household loved.
- Ranks the watchlist, and finds wildcards: films recommended from loved films
  that are neither rated nor on the watchlist.

The scoring is a few lines of arithmetic on purpose, so every pick can say why.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import math
import re
import sys
import time
import urllib.error
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import circle as circle_mod
from . import tmdb
from .search import GENERIC
from .watchlist import fetch, read_film_page

FILMS_PAGE_RE = re.compile(r"/films/page/(\d+)/")
RATED_RE = re.compile(r"\brated-(\d+)\b")
LOVED_STARS = 4.0
GENRE_WEIGHT = 1.5
REC_WEIGHT = 1.0
REC_CAP = 3
CIRCLE_WEIGHT = 1.0  # one 5-star fan adds ~2.4; five add ~5.7 (log-scaled in circle.circle_boost)
WILDCARD_CIRCLE_MIN = 1.0  # circle score that makes an unseen film a wildcard candidate
WILDCARD_LOOKUPS = 250  # TMDB detail calls for wildcard candidates (each cached after the first run)
WILDCARD_MIN_VOTES = 300
WILDCARD_MIN_AVERAGE = 6.8


@dataclass
class RatedFilm:
    slug: str
    title: str
    year: int | None
    stars: float | None  # 0.5 to 5, None when watched but not rated
    liked: bool


def parse_films_page(page_html: str) -> tuple[list[RatedFilm], int]:
    films = []
    for item in page_html.split('<li class="griditem">')[1:]:
        slug = re.search(r'data-item-slug="([^"]+)"', item)
        if not slug:
            continue
        name = html.unescape(re.search(r'data-item-name="([^"]*)"', item).group(1))
        m = re.match(r"^(.*) \((\d{4})\)$", name)
        title, year = (m.group(1), int(m.group(2))) if m else (name, None)
        r = RATED_RE.search(item)
        films.append(RatedFilm(slug.group(1), title, year, int(r.group(1)) / 2 if r else None, "icon-liked" in item))
    pages = [int(p) for p in FILMS_PAGE_RE.findall(page_html)]
    return films, max(pages, default=1)


def read_rated(username: str, delay: float = 1.0) -> list[RatedFilm]:
    base = f"https://letterboxd.com/{username}/films/"
    films, last = parse_films_page(fetch(base))
    if not films:
        raise RuntimeError("films page parsed to zero films; the layout may have changed")
    for n in range(2, last + 1):
        time.sleep(delay)
        try:
            page, _ = parse_films_page(fetch(f"{base}page/{n}/"))
        except urllib.error.HTTPError as e:
            # Letterboxd's bot check blocks every films page after the first
            # (403, Nov 10), so the full history comes from the data export.
            if e.code == 403:
                break
            raise
        films.extend(page)
    return films


def read_export(folder: Path) -> list[RatedFilm]:
    """Letterboxd's own data export (Settings > Data > Export your data), unzipped.

    ratings.csv and likes/films.csv carry Name, Year, Letterboxd URI and Rating.
    The URI is a boxd.it short link, so films are keyed by it and matched on TMDB
    by title and year.
    """
    import csv

    def rows(name):
        path = folder / name
        return list(csv.DictReader(path.open(encoding="utf-8"))) if path.exists() else []

    films: dict[str, RatedFilm] = {}
    for r in rows("watched.csv") + rows("ratings.csv"):
        key = "boxd:" + r["Letterboxd URI"].rstrip("/").rsplit("/", 1)[-1]
        f = films.setdefault(key, RatedFilm(key, r["Name"], int(r["Year"]) if r.get("Year") else None, None, False))
        if r.get("Rating"):
            f.stars = float(r["Rating"])
    for r in rows("likes/films.csv"):
        key = "boxd:" + r["Letterboxd URI"].rstrip("/").rsplit("/", 1)[-1]
        f = films.setdefault(key, RatedFilm(key, r["Name"], int(r["Year"]) if r.get("Year") else None, None, False))
        f.liked = True
    return list(films.values())


def weight(stars: float | None, liked: bool) -> float:
    """5 stars is +1, 4 is +0.5, 3 is neutral, 1 is -1. A heart adds 0.5."""
    w = (stars - 3) / 2 if stars is not None else 0.0
    return w + (0.5 if liked else 0.0)


def loved(e: dict) -> bool:
    return (e.get("stars") or 0) >= LOVED_STARS or bool(e.get("liked"))


def _details(tmdb_id: int) -> dict:
    d = tmdb._get(f"/movie/{tmdb_id}", append_to_response="keywords,recommendations,watch/providers,videos,credits")
    return {**tmdb.people(d),
        "tmdb_id": d["id"],
        "title": d.get("title"),
        "year": int(d["release_date"][:4]) if d.get("release_date") else None,
        "runtime_min": d.get("runtime") or None,
        "genres": [g["name"] for g in d.get("genres", [])],
        "keywords": [k["name"] for k in (d.get("keywords") or {}).get("keywords", [])],
        "rec_ids": [r["id"] for r in (d.get("recommendations") or {}).get("results", [])],
        "vote_average": d.get("vote_average"),
        "vote_count": d.get("vote_count"),
        "overview": d.get("overview") or "",
        "trailer_url": tmdb.pick_trailer((d.get("videos") or {}).get("results", [])),
        "poster_path": d.get("poster_path"),
        "availability": asdict(tmdb.parse_availability(((d.get("watch/providers") or {}).get("results") or {}).get("US"))),
    }


def refresh_rated(username: str, store: dict, log=print, delay: float = 1.0, export: Path | None = None) -> dict:
    """Update the rated-film store in place. Ratings refresh every run; lookups happen once per film."""
    films = read_rated(username, delay)
    log(f"rated: {len(films)} films readable on /{username}/films/")
    if export:
        exported = read_export(export)
        log(f"rated: {len(exported)} films in the data export")
        recent = {(f.title.lower(), f.year) for f in films}
        films += [f for f in exported if (f.title.lower(), f.year) not in recent]  # the live page wins
    for f in films:
        e = store.setdefault(f.slug, {})
        e.update(slug=f.slug, title=f.title, year=f.year, stars=f.stars, liked=f.liked)
        if "tmdb_id" not in e and f.slug.startswith("boxd:"):
            try:
                e["tmdb_id"] = tmdb.search_id(f.title, f.year)
            except urllib.error.URLError as err:
                log(f"  tmdb search failed for {f.title}: {err}")
                continue
        if "tmdb_id" not in e:
            try:
                page = read_film_page(f.slug)
            except urllib.error.URLError as err:
                log(f"  letterboxd page failed for {f.slug}: {err}")
                continue
            finally:
                time.sleep(delay)
            e["tmdb_id"] = page.tmdb_id if page.tmdb_type in (None, "movie") else None
        if e["tmdb_id"] and "keywords" not in e:
            try:
                d = _details(e["tmdb_id"])
            except urllib.error.URLError as err:
                log(f"  tmdb failed for {f.slug}: {err}")
                continue
            e.update(genres=d["genres"], keywords=d["keywords"], rec_ids=d["rec_ids"])
            time.sleep(0.05)
    return store


@dataclass
class Profile:
    keywords: dict[str, float] = field(default_factory=dict)
    genres: dict[str, float] = field(default_factory=dict)
    recommended_by: dict[int, list[str]] = field(default_factory=dict)  # tmdb id -> loved slugs
    loved_keywords: dict[str, list[str]] = field(default_factory=dict)  # keyword -> loved slugs
    rated: dict = field(default_factory=dict)
    circle: dict[int, dict] = field(default_factory=dict)  # tmdb id -> movie_night.circle.scores() entry

    def top_keywords(self, n=15) -> list[tuple[str, float]]:
        return sorted(self.keywords.items(), key=lambda kv: -kv[1])[:n]


def build_profile(rated: dict) -> Profile:
    films = [e for e in rated.values() if e.get("keywords") is not None and e.get("tmdb_id")]
    df = Counter(k for e in films for k in set(e["keywords"]) - GENERIC)
    n = max(len(films), 1)
    p = Profile(rated=rated)
    kw, gw, gcount = defaultdict(float), defaultdict(float), Counter()
    for e in films:
        w = weight(e.get("stars"), e.get("liked", False))
        for k in set(e["keywords"]) - GENERIC:
            kw[k] += w * math.log(1 + n / df[k])
            if loved(e):
                p.loved_keywords.setdefault(k, []).append(e["slug"])
        for g in e.get("genres") or []:
            gw[g] += w
            gcount[g] += 1
        if loved(e):
            for rid in e.get("rec_ids") or []:
                p.recommended_by.setdefault(rid, []).append(e["slug"])
    # Scale so the strongest keyword is 10: keeps keyword, genre and
    # recommendation terms comparable whether there are 70 ratings or 700.
    top = max((abs(v) for v in kw.values()), default=1.0) or 1.0
    p.keywords = {k: 10 * v / top for k, v in kw.items()}
    p.genres = {g: gw[g] / gcount[g] for g in gw}  # mean weight: how the household rates the genre
    return p


@dataclass
class Scored:
    slug: str
    score: float
    reason: str
    parts: dict


def score(entry: dict, p: Profile) -> tuple[float, dict]:
    kws = set(entry.get("keywords") or []) - GENERIC
    s_kw = sum(p.keywords.get(k, 0.0) for k in kws) / math.sqrt(len(kws) + 1)
    genres = entry.get("genres") or []
    s_genre = sum(p.genres.get(g, 0.0) for g in genres) / max(len(genres), 1)
    recs = p.recommended_by.get(entry.get("tmdb_id"), [])
    s_rec = min(len(recs), REC_CAP)
    c = p.circle.get(entry.get("tmdb_id"))
    s_circle = circle_mod.circle_boost(c["score"]) if c else 0.0
    total = s_kw + GENRE_WEIGHT * s_genre + REC_WEIGHT * s_rec + CIRCLE_WEIGHT * s_circle
    return total, {"keywords": round(s_kw, 2), "genres": round(s_genre, 2), "recommended_by": recs,
                   "circle": round(s_circle, 2)}


def reason(entry: dict, p: Profile, parts: dict) -> str:
    """One line naming the loved films this pick most resembles."""
    votes = Counter()
    for slug in parts["recommended_by"]:
        votes[slug] += 3
    for k in set(entry.get("keywords") or []) - GENERIC:
        if p.keywords.get(k, 0) > 0:
            for slug in p.loved_keywords.get(k, []):
                votes[slug] += 1
    names = []
    for slug, _ in votes.most_common(2):
        e = p.rated[slug]
        stars = f"{e['stars']:g}★" if e.get("stars") else "♥"
        names.append(f"{e['title']} ({stars})")
    shared = sorted((k for k in set(entry.get("keywords") or []) - GENERIC if p.keywords.get(k, 0) > 0),
                    key=lambda k: -p.keywords[k])[:3]
    out = "Like " + " and ".join(names) if names else "Fits your genres"
    return out + (f"; shares {', '.join(shared)}" if shared else "")


def rank(cache: dict, p: Profile) -> list[Scored]:
    seen = {e.get("tmdb_id") for e in p.rated.values() if e.get("tmdb_id")}
    out = []
    for slug, e in cache.items():
        if not e.get("on_watchlist") or not e.get("tmdb_id") or e["tmdb_id"] in seen:
            continue  # already watched (e.g. saved for a rewatch): not a pick
        s, parts = score(e, p)
        out.append(Scored(slug, s, reason(e, p, parts), parts))
    return sorted(out, key=lambda x: -x.score)


def wildcards(cache: dict, p: Profile, store: dict, lookups: int = WILDCARD_LOOKUPS, log=print) -> list[Scored]:
    """Films the household hasn't rated or saved: recommended from loved films, or loved by the circle."""
    seen = {e.get("tmdb_id") for e in p.rated.values()} | {e.get("tmdb_id") for e in cache.values()}
    circle = sorted((t for t, c in p.circle.items() if c["score"] >= WILDCARD_CIRCLE_MIN and t not in seen),
                    key=lambda t: -p.circle[t]["score"])
    recs = sorted((rid for rid in p.recommended_by if rid not in seen), key=lambda r: -len(p.recommended_by[r]))
    cands = list(dict.fromkeys(circle + recs))
    out = []
    for rid in cands[:lookups + len(circle)]:
        key = str(rid)
        if key not in store:
            try:
                store[key] = _details(rid)
            except urllib.error.URLError as err:
                log(f"  tmdb failed for wildcard {rid}: {err}")
                continue
            time.sleep(0.05)
        e = store[key]
        new_release = (e.get("year") or 0) >= dt.date.today().year - 1  # too new for many votes
        if not (rid in p.circle and new_release) and (
                (e.get("vote_count") or 0) < WILDCARD_MIN_VOTES or (e.get("vote_average") or 0) < WILDCARD_MIN_AVERAGE):
            continue
        s, parts = score(e, p)
        out.append(Scored(key, s, reason(e, p, parts), parts))
    return sorted(out, key=lambda x: -x.score)


def _where(e: dict) -> str:
    return tmdb.Availability(**e["availability"]).where() or "Not streaming" if e.get("availability") else "?"


def report(cache: dict, p: Profile, ranked: list[Scored], wild: list[Scored], store: dict) -> str:
    rated = [e for e in p.rated.values() if e.get("stars") is not None]
    lines = ["# Household taste profile", "",
             f"{len(p.rated)} films watched, {len(rated)} rated, "
             f"{sum(1 for e in p.rated.values() if loved(e))} loved (4+ stars or a heart).", "",
             "## What you love (top keywords)", "",
             ", ".join(f"{k} ({v:.1f})" for k, v in p.top_keywords(20)), "",
             "## Genres, by average weight", "",
             ", ".join(f"{g} {v:+.2f}" for g, v in sorted(p.genres.items(), key=lambda kv: -kv[1])), "",
             "## Top 20 from the watchlist", "",
             "| # | Film | Where | Score | Why |", "|---|---|---|---|---|"]
    for i, s in enumerate(ranked[:20], 1):
        e = cache[s.slug]
        lines.append(f"| {i} | {e['title']} ({e.get('year')}) | {_where(e)} | {s.score:.1f} | {s.reason} |")
    lines += ["", "## Bottom 5 from the watchlist (least like what you love)", "",
              "| Film | Score | Why |", "|---|---|---|"]
    for s in ranked[-5:]:
        e = cache[s.slug]
        lines.append(f"| {e['title']} ({e.get('year')}) | {s.score:.1f} | genres {s.parts['genres']:+.2f} |")
    lines += ["", "## Top 10 wildcards (not rated, not on the watchlist)", "",
              "| # | Film | Where | TMDB | Score | Why |", "|---|---|---|---|---|---|"]
    for i, s in enumerate(wild[:10], 1):
        e = store[s.slug]
        lines.append(f"| {i} | {e['title']} ({e.get('year')}) | {_where(e)} | {e['vote_average']:.1f} | "
                     f"{s.score:.1f} | {s.reason} |")
    return "\n".join(lines) + "\n"


def short_reason(r: str) -> str:
    """The pick-message version: just the loved films, not the shared tags."""
    return r.split("; ")[0]


def pick_reason(s: Scored, e: dict, p: Profile) -> str:
    """What Delo says under a pick: the loved films it resembles, then the circle's voice if any."""
    lines = [short_reason(s.reason)] if s.parts["keywords"] > 0 or s.parts["recommended_by"] else []
    c = p.circle.get(e.get("tmdb_id"))
    v = circle_mod.voice(c) if c and c["score"] > 0 else None
    if v:
        lines.append("💬 " + v)
    return "\n".join(lines) or short_reason(s.reason)


def build(username: str, data: Path, export: Path | None = None, refresh: bool = True, log=print,
          keep_wild: int = 30) -> dict:
    """Refresh ratings and write data/taste.json, which Delo reads at kickoff."""
    rated_path, wild_path = data / "rated.json", data / "wildcards.json"
    store = json.loads(rated_path.read_text()) if rated_path.exists() else {}
    if refresh:
        refresh_rated(username, store, log, export=export)
        rated_path.write_text(json.dumps(store, indent=1, ensure_ascii=False))
    cache = json.loads((data / "films.json").read_text())
    p = build_profile(store)
    p.circle = circle_mod.scores(circle_mod.load(data))
    wstore = json.loads(wild_path.read_text()) if wild_path.exists() else {}
    wild = wildcards(cache, p, wstore, log=log)[:keep_wild]
    today = dt.date.today().isoformat()
    for w in wild:  # availability changes; the rest of a film's details don't
        e = wstore[w.slug]
        if e.get("availability_checked") != today:
            try:
                us = tmdb._get(f"/movie/{e['tmdb_id']}/watch/providers").get("results", {}).get("US")
                e["availability"], e["availability_checked"] = asdict(tmdb.parse_availability(us)), today
            except urllib.error.URLError as err:
                log(f"  availability failed for wildcard {e['title']}: {err}")
            time.sleep(0.05)
    wild_path.write_text(json.dumps(wstore, indent=1, ensure_ascii=False))
    out = {
        "built": dt.datetime.now(dt.timezone.utc).isoformat(),
        "rated": len(store),
        "scores": {s.slug: [round(s.score, 2), pick_reason(s, cache[s.slug], p)] for s in rank(cache, p)},
        "wildcards": {f"tmdb-{w.slug}": {**{k: wstore[w.slug].get(k) for k in (
            "tmdb_id", "title", "year", "runtime_min", "genres", "availability", "trailer_url",
            "poster_path", "keywords", "overview", "directors", "cast", "countries", "language")},
            "wildcard": True, "on_watchlist": False, "score": round(w.score, 2),
            "reason": pick_reason(w, wstore[w.slug], p)}
            for w in wild},
    }
    (data / "taste.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    log(f"taste: profile from {len(store)} films, {len(out['scores'])} watchlist scores, {len(wild)} wildcards")
    return out


def load(data: Path) -> dict | None:
    path = data / "taste.json"
    try:
        return json.loads(path.read_text()) if path.exists() else None
    except json.JSONDecodeError:
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("username")
    ap.add_argument("--data", type=Path, default=Path("data"))
    ap.add_argument("--report", type=Path)
    ap.add_argument("--no-refresh", action="store_true", help="use data/rated.json as is")
    ap.add_argument("--export", type=Path, help="unzipped Letterboxd data export, for the full rating history")
    args = ap.parse_args(argv)
    log = lambda m: print(m, file=sys.stderr)  # noqa: E731
    rated_path, wild_path = args.data / "rated.json", args.data / "wildcards.json"
    store = json.loads(rated_path.read_text()) if rated_path.exists() else {}
    if not args.no_refresh:
        refresh_rated(args.username, store, log, export=args.export)
        rated_path.write_text(json.dumps(store, indent=1, ensure_ascii=False))
    cache = json.loads((args.data / "films.json").read_text())
    p = build_profile(store)
    p.circle = circle_mod.scores(circle_mod.load(args.data))
    wstore = json.loads(wild_path.read_text()) if wild_path.exists() else {}
    wild = wildcards(cache, p, wstore, log=log)
    wild_path.write_text(json.dumps(wstore, indent=1, ensure_ascii=False))
    text = report(cache, p, rank(cache, p), wild, wstore)
    if args.report:
        args.report.write_text(text)
    else:
        print(text)


if __name__ == "__main__":
    main()
