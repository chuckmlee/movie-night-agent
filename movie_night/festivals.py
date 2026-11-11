"""What critics thought at the festival, from cannes-ratings (Chuck, Nov 11).

Reini Urban's cannes-ratings (https://cannes-ratings.org, data on GitHub at
rurban/cannes-ratings) collects critics' scores from the big festivals each year:
Screen Daily's jury grid, Le film français, ioncinema, critic.de, the ICS panel,
Moiree and individual reviews, each converted to a 0-10 scale (the file headers
say how). It covers Cannes since 2010, Sundance since 2015, Berlinale since 2016
and Venice since 2025.

That matters most for new festival films: months before Rotten Tomatoes or
Metacritic have much to say, two dozen critics have already scored them. So for
each film Delo keeps:

- critics: the mean of the critics' scores (not the Letterboxd users the files
  also list), and how many there were
- awards: the jury prizes, merged into honors when Wikidata hasn't caught up

The data files are fetched from raw.githubusercontent.com and parsed into
data/festivals.json. Past years are fetched once; this year's and last year's
are refetched weekly while the festivals run. Films are matched to Delo's by
title (English or original) and year, and by director when both sides know it.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

from . import honors as honors_mod

RAW = "https://raw.githubusercontent.com/rurban/cannes-ratings/master/public/{name}.dat"
UA = "movie-night-agent/0.1 (personal project; https://github.com/chuckmlee/movie-night-agent)"
FIRST_YEAR = {"Cannes": 2010, "Sundance": 2015, "Berlinale": 2016, "Venice": 2025}
FRESH_DAYS = 7  # this year's and last year's files, while ratings still come in
OLD_DAYS = 180  # older files barely change
MIN_CRITICS = 5  # fewer than this and the mean says more about who showed up
TOP_SHARE = 0.25  # festival means bunch up (a Grand Prix winner can average 6.5), so the line shows rank

FILM = re.compile(r'^"(.+?)"\s*(?:\(([^)]*)\))?\s*(?:\[([^\]]*)\])?\s*(.*)$')
SCORE = re.compile(r"^(\S.*?)\s+(\d{1,2}(?:\.\d+)?)(?:\s+https?://\S+)?\s*$")
ALSO = re.compile(r"\b(?:was|also):\s*(.+?)\s*$")
HEADING = re.compile(r"^[A-Z][A-Z .&'-]+$")

# Jury prizes, mapped to the names honors.py uses, by festival. Only main-competition
# sections count: "Jury Prize" in Un Certain Regard is a different prize.
MAIN = {"competition", "wettbewerb", "u.s. dramatic", "world dramatic", "concorso"}
PRIZES = {
    "Cannes": [("Palme d'Or", r"(?<!Special )Palme d'Or"), ("Grand Prix, Cannes", r"(?<!Special )Grand Prix\b"),
               ("Cannes Jury Prize", r"(?<!Special )Jury Prize"), ("Best Director, Cannes", r"Best Director")],
    "Venice": [("Golden Lion", r"Golden Lion"), ("Venice Grand Jury Prize", r"Grand Jury Prize"),
               ("Silver Lion", r"Silver Lion|Best Director")],
    "Berlinale": [("Golden Bear", r"Golden Bear"), ("Silver Bear", r"Silver Bear|Grand Jury Prize|Best Direction")],
    "Sundance": [("Sundance Grand Jury Prize", r"Grand Jury Prize")],
}
ANY_SECTION = [("Caméra d'Or", r"Cam[eé]ra d'Or")]


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c)).replace("&", " and ")
    words = re.sub(r"[^\w\s]", " ", s).split()
    return " ".join(w for w in words if w not in {"a", "an", "the"})


def titles(raw: str) -> list[str]:
    """"After (Sirat)" -> ["After", "Sirat", "After (Sirat)"]: the English and original titles."""
    out = [raw]
    m = re.match(r"^(.+?)\s*\((.+)\)$", raw)
    if m:
        out[:0] = [m.group(1), m.group(2)]
    return out


def _names(s: str) -> set[str]:
    """Name words long enough to compare: "Luc+Jean-Pierre Dardenne" -> {"luc", "jean", "pierre", "dardenne"}."""
    return {w for w in norm(s).split() if len(w) >= 3}


def awards(festival: str, section: str, text: str) -> list[str]:
    main = (section or "").strip().lower() in MAIN
    out = []
    for name, pat in (PRIZES.get(festival, []) if main else []) + ANY_SECTION:
        if re.search(pat, text or "") and name not in out:
            out.append(name)
    return out


def parse(text: str, festival: str, year: int) -> list[dict]:
    """One cannes-ratings .dat file -> [{"titles", "director", "section", "awards", "critics", "n"}]."""
    start = text.find("<<'EOF';")
    body = text[start:].split("\n", 1)[1] if start >= 0 else text
    films, cur, source, seen = [], None, "", set()

    def close():
        if cur:
            scores = cur.pop("_scores")
            cur["n"] = len(scores)
            cur["critics"] = round(sum(scores) / len(scores), 2) if scores else None
            if cur["n"] or cur["awards"]:
                films.append(cur)

    for ln in body.splitlines():
        if ln.startswith("EOF"):
            break
        s = ln.rstrip()
        if HEADING.match(s):
            if s.startswith("PREDICTIONS"):
                break
            continue
        m = FILM.match(s)
        if m:
            close()
            title, director, section, rest = m.groups()
            cur = {"titles": titles(title), "director": (director or "").split(",")[0].strip(),
                   "section": (section or "").strip(), "awards": awards(festival, section or "", rest),
                   "festival": festival, "year": year, "_scores": []}
            source, seen = "", set()
            continue
        if cur is None or not s.strip():
            continue
        if s.startswith("#"):
            # "#bunsen_   8" or "#Carlota Moseguí     " is a critic commented out, not a new source
            if not re.search(r"\s\d{1,2}(\.\d+)?$", s) and not re.search(r"\S\s{2,}$", ln):
                source = s[1:].strip().lower()
            continue
        if s[0].isspace():
            a = ALSO.search(s)
            if a:
                cur["titles"].append(a.group(1))
            continue
        sc = SCORE.match(s)
        if not sc or "letterboxd" in source:
            continue
        who, v = sc.group(1).strip().lower(), float(sc.group(2))
        if v <= 10 and who not in seen:  # some critics are listed twice, once per outlet
            seen.add(who)
            cur["_scores"].append(v)
    close()
    rated = sorted((f for f in films if f["n"] >= MIN_CRITICS), key=lambda f: -f["critics"])
    for i, f in enumerate(rated, 1):
        f["rank"], f["of"] = i, len(rated)
    return films


def _fetch(name: str) -> str | None:
    req = urllib.request.Request(RAW.format(name=name), headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None  # not published (yet)
        raise


def files(today: dt.date) -> list[tuple[str, int]]:
    return [(f, y) for f, first in FIRST_YEAR.items() for y in range(first, today.year + 1)]


def refresh(data: Path, fetch=_fetch, today: dt.date | None = None, log=print, pause: float = 1.0) -> dict:
    """Fetch the files that are missing or due, and rewrite data/festivals.json."""
    today = today or dt.date.today()
    store = load(data)
    got = 0
    for festival, year in files(today):
        name = f"{festival}{year}"
        rec = store.get(name) or {}
        days = FRESH_DAYS if year >= today.year - 1 else OLD_DAYS
        if rec.get("fetched", "") >= (today - dt.timedelta(days=days)).isoformat():
            continue
        try:
            text = fetch(name)
        except (urllib.error.URLError, TimeoutError) as e:
            log(f"festivals: {name} failed: {e!r}")
            break
        store[name] = {"fetched": today.isoformat(), "films": parse(text, festival, year) if text else []}
        got += 1
        time.sleep(pause)
    (data / "festivals.json").write_text(json.dumps(store, ensure_ascii=False))
    n = sum(len(v["films"]) for v in store.values())
    log(f"festivals: fetched {got} files, {n} festival films")
    return store


def load(data: Path) -> dict:
    path = data / "festivals.json"
    try:
        return json.loads(path.read_text()) if path.exists() else {}
    except json.JSONDecodeError:
        return {}


def index(store: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for rec in store.values():
        for f in rec.get("films", []):
            for t in {norm(t) for t in f["titles"]}:
                out.setdefault(t, []).append(f)
    return out


_memo: dict = {}


def cached_index(data: Path) -> dict[str, list[dict]]:
    """index(load(data)), reread only when the file changes: Delo polls every few seconds."""
    path = data / "festivals.json"
    stamp = path.stat().st_mtime if path.exists() else None
    if _memo.get("key") != (str(path), stamp):
        _memo.update(key=(str(path), stamp), idx=index(load(data)))
    return _memo["idx"]


def match(entry: dict, idx: dict[str, list[dict]]) -> dict | None:
    """The festival film this entry is, or None. A film premieres at a festival in its TMDB
    year or the year before; when both sides name a director, they must share a name."""
    year = entry.get("year")
    mine = set().union(*(_names(d) for d in entry.get("directors") or [])) if entry.get("directors") else set()
    best = None
    for f in idx.get(norm(entry.get("title") or ""), []):
        if not year or not year - 1 <= f["year"] <= year + 1:
            continue
        theirs = _names(f["director"])
        if mine and theirs and not mine & theirs:
            continue
        if not mine and f["year"] not in (year, year - 1):
            continue
        if best is None or f["n"] > best["n"]:  # a film can play two festivals; keep the better-rated sample
            best = f
    return best


def annotate(cache: dict, idx: dict[str, list[dict]]) -> None:
    """entry["festival"] = {"name": "Cannes 2025", "critics": 7.8, "n": 24, "section": ...},
    and festival prizes added to entry["honors"] when Wikidata doesn't have them yet.
    Run it after honors.annotate. `idx` is index(store) or cached_index(data)."""
    for e in cache.values():
        f = match(e, idx) if idx else None
        if not f:
            e.pop("festival", None)
            continue
        rated = f["n"] >= MIN_CRITICS
        e["festival"] = {"name": f"{f['festival']} {f['year']}", "section": f["section"], "n": f["n"],
                         "critics": f["critics"] if rated else None,
                         "rank": f.get("rank") if rated else None, "of": f.get("of") if rated else None}
        if f["awards"]:
            h = e.setdefault("honors", {"wins": [], "criterion": None})
            order = [name for name, _ in honors_mod.NOTABLE]
            h["wins"] = sorted(set(h["wins"]) | set(f["awards"]), key=lambda w: order.index(w) if w in order else 99)


def percentile(e: dict) -> float | None:
    """Where the festival's critics placed it among that year's films, 0-100 (100 = their favorite)."""
    f = e.get("festival") or {}
    if not f.get("rank") or not f.get("of"):
        return None
    return 100.0 if f["of"] == 1 else 100.0 * (f["of"] - f["rank"]) / (f["of"] - 1)


def line(e: dict) -> str | None:
    """"🎟️ Cannes 2025 critics: #9 of 93 (6.9/10)" when the critics there ranked it near the top."""
    f = e.get("festival") or {}
    if not f.get("rank") or f["rank"] > max(3, round(f["of"] * TOP_SHARE)):
        return None
    return f"🎟️ {f['name']} critics: #{f['rank']} of {f['of']} ({f['critics']:.1f}/10)"
