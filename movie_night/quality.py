"""A blended quality score per film: how good it is by consensus, 0 to 100.

This sits beside the taste profile, which says how well a film suits the
household. Picks rank on both (picker.FIT_SHARE).

Sources, each turned into a percentile among every film Delo knows so their
scales compare (IMDb clusters around 6 to 8, Letterboxd around 3 to 4):

    Letterboxd average                    30%
    Critics: mean of Tomatometer and Metacritic   30%
    IMDb                                  15%
    Trusted circle (not a percentile: how many people loved it, with diminishing returns)  25%

A missing source doesn't count against a film: its weight is spread over the
sources the film has. `sources` says how many there were, so a score built on
one source can be shown as low confidence.

IMDb, Rotten Tomatoes and Metacritic come from OMDb (OMDB_API_KEY, free tier
1,000 calls a day), cached in data/ratings.json and refreshed every 30 days.
"""

from __future__ import annotations

import bisect
import datetime as dt
import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import circle as circle_mod

WEIGHTS = {"letterboxd": 0.30, "critics": 0.30, "imdb": 0.15, "circle": 0.25}
MIN_IMDB_VOTES = 500  # below this an IMDb average is mostly noise
DAILY_BUDGET = 900  # OMDb free tier is 1,000 a day; leave room for retries
REFRESH_DAYS = 30
OMDB = "https://www.omdbapi.com/"


def key(entry: dict) -> str | None:
    return f"tmdb-{entry['tmdb_id']}" if entry.get("tmdb_id") else None


def parse_omdb(d: dict) -> dict:
    """OMDb's answer -> {"imdb": 7.8, "imdb_votes": 120000, "rt": 92, "mc": 80}, with missing values left out."""
    out = {}
    try:
        if d.get("imdbRating") not in (None, "N/A"):
            out["imdb"] = float(d["imdbRating"])
        if d.get("imdbVotes") not in (None, "N/A"):
            out["imdb_votes"] = int(d["imdbVotes"].replace(",", ""))
    except ValueError:
        pass
    for r in d.get("Ratings") or []:
        m = re.match(r"(\d+)", r.get("Value") or "")
        if m and r.get("Source") == "Rotten Tomatoes":
            out["rt"] = int(m.group(1))
        elif m and r.get("Source") == "Metacritic":
            out["mc"] = int(m.group(1))
    if "mc" not in out and (d.get("Metascore") or "N/A") != "N/A":
        out["mc"] = int(d["Metascore"])
    return out


def _omdb(imdb_id: str, api_key: str) -> dict:
    url = OMDB + "?" + urllib.parse.urlencode({"i": imdb_id, "apikey": api_key})
    with urllib.request.urlopen(url, timeout=20) as resp:
        return json.loads(resp.read())


def _imdb_id(tmdb_id: int) -> str | None:
    from . import tmdb
    return tmdb._get(f"/movie/{tmdb_id}/external_ids").get("imdb_id") or None


class OutOfCalls(Exception):
    pass


def refresh(entries: dict, data: Path, api_key: str | None = None, budget: int = DAILY_BUDGET,
            fetch=_omdb, imdb_id=_imdb_id, today: dt.date | None = None, log=print) -> dict:
    """Fill data/ratings.json for films without ratings (or with stale ones), oldest first, within budget."""
    api_key = api_key or os.environ.get("OMDB_API_KEY", "").strip().strip('"').strip("'")
    path = data / "ratings.json"
    store = json.loads(path.read_text()) if path.exists() else {}
    if not api_key:
        log("ratings: no OMDB_API_KEY, skipping")
        return store
    today = today or dt.date.today()
    stale = (today - dt.timedelta(days=REFRESH_DAYS)).isoformat()
    todo = []
    for e in entries.values():
        k = key(e)
        if k and (k not in store or store[k].get("fetched", "") < stale):
            todo.append((store.get(k, {}).get("fetched", ""), k, e))
    todo.sort(key=lambda t: t[0])  # never-fetched first
    done = 0
    try:
        for _, k, e in todo[:budget]:
            rec = store.get(k, {})
            try:
                rec["imdb_id"] = rec.get("imdb_id") or imdb_id(e["tmdb_id"])
                if rec["imdb_id"]:
                    d = fetch(rec["imdb_id"], api_key)
                    if d.get("Response") == "False":
                        err = d.get("Error", "")
                        if "limit" in err.lower() or "invalid api key" in err.lower():
                            raise OutOfCalls(err)
                    else:
                        rec.update({f: None for f in ("imdb", "imdb_votes", "rt", "mc")}, **parse_omdb(d))
            except urllib.error.HTTPError as err:
                if err.code == 401:
                    raise OutOfCalls("OMDb returned 401 (key not activated yet?)")
                continue
            except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
                continue
            rec["fetched"] = today.isoformat()
            store[k] = rec
            done += 1
            if done % 50 == 0:
                path.write_text(json.dumps(store, indent=1))
    except OutOfCalls as err:
        log(f"ratings: stopped early: {err}")
    path.write_text(json.dumps(store, indent=1))
    log(f"ratings: fetched {done}, {max(0, len(todo) - done)} left for later, {len(store)} cached")
    return store


def _percentiles(values: dict[str, float]) -> dict[str, float]:
    """Each value's percentile (0-100) among all of them; ties share the middle rank."""
    ordered = sorted(values.values())
    n = len(ordered)
    if n < 2:
        return {k: 50.0 for k in values}
    out = {}
    for k, v in values.items():
        lo, hi = bisect.bisect_left(ordered, v), bisect.bisect_right(ordered, v)
        out[k] = 100.0 * ((lo + hi - 1) / 2) / (n - 1)
    return out


def circle_points(score: float) -> float:
    """The circle's 0-100: one 5-star fan ~55, two ~70, five ~85; a lukewarm or negative circle 0."""
    return 100.0 * (1 - math.exp(-max(0.0, circle_mod.circle_boost(score)) / 3))


def blend(entries: dict, ratings: dict, circle: dict[int, dict] | None = None,
          weights: dict[str, float] = WEIGHTS) -> dict[str, dict]:
    """Per film key: {"score": 0-100, "sources": n, "parts": {source: 0-100}}."""
    circle = circle or {}
    raw: dict[str, dict[str, float]] = {"letterboxd": {}, "critics": {}, "imdb": {}}
    films = {}
    for e in entries.values():
        k = key(e)
        if not k:
            continue
        films[k] = e
        r = ratings.get(k) or {}
        if e.get("letterboxd_rating"):
            raw["letterboxd"][k] = e["letterboxd_rating"]
        crit = [v for v in (r.get("rt"), r.get("mc")) if v is not None]
        if crit:
            raw["critics"][k] = sum(crit) / len(crit)
        if r.get("imdb") is not None and (r.get("imdb_votes") or 0) >= MIN_IMDB_VOTES:
            raw["imdb"][k] = r["imdb"]
    pct = {src: _percentiles(vals) for src, vals in raw.items()}
    out = {}
    for k, e in films.items():
        parts = {src: round(p[k], 1) for src, p in pct.items() if k in p}
        c = circle.get(e.get("tmdb_id"))
        if c:
            parts["circle"] = round(circle_points(c["score"]), 1)
        if not parts:
            continue
        w = sum(weights[s] for s in parts)
        r = ratings.get(k) or {}
        raw_vals = {"letterboxd": e.get("letterboxd_rating"), "rt": r.get("rt"), "mc": r.get("mc"),
                    "imdb": r.get("imdb") if "imdb" in parts else None,
                    "fans": sum(1 for p in (c or {}).get("people", []) if p.get("signal", 0) > 0)}
        out[k] = {"score": round(sum(weights[s] * v for s, v in parts.items()) / w, 1),
                  "sources": len(parts), "parts": parts, "raw": {a: b for a, b in raw_vals.items() if b}}
    return out


SPLIT = 35  # percentile gap between critics and audiences that is worth saying out loud


def highlight(q: dict, skip_circle: bool = False) -> str | None:
    """The one thing that best explains a film's score (Chuck, Nov 11):
    the circle's love first, then a sharp critics/audience split, then the best source."""
    parts, raw = q.get("parts") or {}, q.get("raw") or {}
    fans = raw.get("fans", 0)
    if fans and parts.get("circle", 0) > 0 and not skip_circle:  # skipped when the pick already quotes them
        return "someone you follow loved it" if fans == 1 else f"{fans} people you follow loved it"
    aud = [parts[s] for s in ("letterboxd", "imdb") if s in parts]
    if "critics" in parts and aud:
        gap = parts["critics"] - sum(aud) / len(aud)
        if gap >= SPLIT:
            return "critics love it, fans split"
        if gap <= -SPLIT:
            return "fans love it, critics split"
    best = max((s for s in parts if s != "circle"), key=lambda s: parts[s], default=None)
    if best == "critics":
        crit = f"{raw['rt']}% on Rotten Tomatoes" if raw.get("rt") is not None else f"{raw.get('mc')} on Metacritic"
        return "critics' favorite" if parts["critics"] >= 70 else crit  # the full figure wouldn't fit one line
    if best == "letterboxd" and raw.get("letterboxd"):
        return f"★ {raw['letterboxd']:.1f} on Letterboxd"
    if best == "imdb" and raw.get("imdb"):
        return f"{raw['imdb']:.1f} on IMDb"
    return None


HEADER_WIDTH = 38  # characters that fit on one line of a pick bubble next to nothing else


def line(entry: dict, skip_circle: bool = False) -> str | None:
    """The score line under a pick's title: "86/100 · critics' favorite (94% on Rotten Tomatoes)",
    shortened to "86/100 · critics' favorite" when it wouldn't fit on one line.

    One source isn't enough for a number that looks certain, so then it's that
    source as-is ("★ 4.1 on Letterboxd"), as before the blended score."""
    q = entry.get("quality_info")
    lb = entry.get("letterboxd_rating")
    if not q or q.get("sources", 0) < 2:
        return f"★ {lb:.1f} on Letterboxd" if lb else None
    h = highlight(q, skip_circle)
    out = f"{round(q['score'])}/100" + (f" · {h}" if h else "")
    if len(out) > HEADER_WIDTH:
        out = re.sub(r"\s*\([^)]*\)$", "", out)
    return out
