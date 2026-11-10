"""M1 daily sync: watchlist -> film cache -> availability snapshot.

Run once a day:  python3 -m movie_night.sync chucklee

- Reads the shared Letterboxd watchlist.
- For films new to the cache, reads the Letterboxd film page once (TMDB id and
  rating) and pulls runtime, genres and trailer from TMDB.
- Refreshes Letterboxd ratings older than a week, a few dozen per run, so the
  Letterboxd load stays at roughly one page per second for a few minutes.
- Checks every film's US availability on TMDB and writes a dated snapshot.

Files (git-ignored): data/films.json, data/availability/YYYY-MM-DD.json.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import urllib.error
from dataclasses import asdict
from pathlib import Path

from . import tmdb
from .watchlist import read_film_page, read_watchlist

DATA = Path("data")
RATING_MAX_AGE_DAYS = 7
RATING_REFRESH_PER_RUN = 40
LETTERBOXD_DELAY = 1.0
TMDB_DELAY = 0.05


def load_cache(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False))
    tmp.replace(path)


def _apply_page(entry: dict, page, today: str) -> None:
    entry["tmdb_id"] = page.tmdb_id if page.tmdb_type in (None, "movie") else None
    entry["tmdb_type"] = page.tmdb_type
    entry["letterboxd_rating"] = page.rating
    entry["letterboxd_rating_count"] = page.rating_count
    entry["rating_checked"] = today


def sync(username: str, data: Path = DATA, limit: int | None = None, log=print) -> dict:
    today = dt.date.today().isoformat()
    cache_path = data / "films.json"
    cache = load_cache(cache_path)

    films = read_watchlist(username)
    if limit:
        films = films[:limit]
    log(f"watchlist: {len(films)} films")
    on_list = {f.slug for f in films}

    for slug, entry in cache.items():
        entry["on_watchlist"] = slug in on_list

    stats = {"new": 0, "rating_refreshed": 0, "enrich_failed": 0, "no_tmdb": 0}
    stale_budget = RATING_REFRESH_PER_RUN
    for f in films:
        entry = cache.setdefault(f.slug, {})
        entry.update(asdict(f))
        entry["on_watchlist"] = True
        is_new = "rating_checked" not in entry
        age = (dt.date.today() - dt.date.fromisoformat(entry["rating_checked"])).days if not is_new else None
        if is_new or (age >= RATING_MAX_AGE_DAYS and stale_budget > 0):
            try:
                _apply_page(entry, read_film_page(f.slug), today)
            except urllib.error.URLError as e:
                log(f"  letterboxd page failed for {f.slug}: {e}")
                continue
            finally:
                time.sleep(LETTERBOXD_DELAY)
            if is_new:
                stats["new"] += 1
            else:
                stale_budget -= 1
                stats["rating_refreshed"] += 1

        if entry.get("tmdb_id") is None and entry.get("tmdb_type") != "tv" and not entry.get("tmdb_searched"):
            entry["tmdb_id"] = tmdb.search_id(f.title, f.year)
            entry["tmdb_searched"] = True
        if entry.get("tmdb_id") is None:
            stats["no_tmdb"] += 1
            continue
        if "runtime_min" not in entry:
            try:
                e = tmdb.enrich(entry["tmdb_id"])
            except urllib.error.URLError as err:
                log(f"  tmdb failed for {f.slug}: {err}")
                stats["enrich_failed"] += 1
                continue
            entry.update(runtime_min=e.runtime_min, genres=e.genres, trailer_url=e.trailer_url,
                         overview=e.overview, availability=asdict(e.availability), availability_checked=today,
                         keywords=e.keywords, poster_path=e.poster_path)
            time.sleep(TMDB_DELAY)
        elif "keywords" not in entry:  # backfill for films cached before keywords existed
            try:
                entry["keywords"] = tmdb.keywords(entry["tmdb_id"])
            except urllib.error.HTTPError as err:
                if err.code == 404:
                    entry["keywords"] = []  # TMDB doesn't know this id; don't retry every boot
                log(f"  tmdb keywords failed for {f.slug}: {err}")
            except urllib.error.URLError as err:
                log(f"  tmdb keywords failed for {f.slug}: {err}")
            time.sleep(TMDB_DELAY)
        save_json(cache_path, cache)

    # Daily availability snapshot for everything still on the list.
    snapshot = {}
    for slug in on_list:
        entry = cache.get(slug, {})
        if entry.get("tmdb_id") is None:
            continue
        if entry.get("availability_checked") != today:
            try:
                us = tmdb._get(f"/movie/{entry['tmdb_id']}/watch/providers").get("results", {}).get("US")
            except urllib.error.URLError as err:
                log(f"  availability failed for {slug}: {err}")
                continue
            entry["availability"] = asdict(tmdb.parse_availability(us))
            entry["availability_checked"] = today
            time.sleep(TMDB_DELAY)
        snapshot[slug] = entry["availability"]
    save_json(cache_path, cache)
    save_json(data / "availability" / f"{today}.json", snapshot)
    # Written only when a run reaches the end, so a sync cut off by a restart
    # is redone on the next boot (Railway, Nov 10).
    save_json(data / "sync-complete.json", {"at": dt.datetime.now(dt.timezone.utc).isoformat(), "films": len(on_list)})

    included = sum(1 for a in snapshot.values() if a["included"])
    stats.update(on_watchlist=len(on_list), with_availability=len(snapshot), streaming_on_household=included)
    log(json.dumps(stats))
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("username")
    ap.add_argument("--data", type=Path, default=DATA)
    ap.add_argument("--limit", type=int, help="only the first N watchlist films (for testing)")
    args = ap.parse_args(argv)
    sync(args.username, args.data, args.limit, log=lambda m: print(m, file=sys.stderr))


if __name__ == "__main__":
    main()
