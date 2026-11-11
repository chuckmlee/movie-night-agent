"""Festival prizes, major awards and the Criterion Collection, from Wikidata (Chuck, Nov 11).

Wikidata is open (CC0) and keyed by TMDB id (property P4947), so one SPARQL query
answers ~150 films. For each film we keep:

- wins: notable awards won (P166), filtered to festival top prizes and the major
  Academy Awards, most prestigious first
- criterion: its Criterion Collection spine number (P12279), True when Criterion
  lists it (P9584) without a spine, or None

Cached in data/honors.json and refreshed every 30 days. These are signals for
less-hyped films: a Golden Bear winner with 900 TMDB votes is exactly the kind of
pick the household is after.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SPARQL = "https://query.wikidata.org/sparql"
UA = "movie-night-agent/0.1 (personal project; https://github.com/chuckmlee/movie-night-agent)"
BATCH = 150
REFRESH_DAYS = 30

# Most prestigious first; a win's label must match one of these to count.
NOTABLE = [
    ("Palme d'Or", r"^Palme d'Or$"),
    ("Golden Lion", r"^Golden Lion$"),
    ("Golden Bear", r"^Golden Bear$"),
    ("Grand Prix, Cannes", r"^Grand Prix \(Cannes"),
    ("Oscar, Best Picture", r"^Academy Award for Best Picture$"),
    ("Oscar, Best International Feature", r"^Academy Award for Best (International Feature|Foreign Language) Film$"),
    ("Silver Bear", r"^Silver Bear"),
    ("Silver Lion", r"^Silver Lion"),
    ("Venice Grand Jury Prize", r"^Grand Jury Prize \(Venice"),
    ("Cannes Jury Prize", r"^Jury Prize \(Cannes"),
    ("Caméra d'Or", r"^Caméra d'Or$"),
    ("Golden Leopard", r"^Golden Leopard$"),
    ("Sundance Grand Jury Prize", r"^Sundance Grand Jury Prize"),
    ("Oscar, Best Director", r"^Academy Award for Best Director$"),
    ("Oscar, Best Original Screenplay", r"^Academy Award for Best (Writing, )?Original Screenplay$"),
    ("Oscar, Best Adapted Screenplay", r"^Academy Award for Best (Writing, )?Adapted Screenplay$"),
    ("Best Director, Cannes", r"^Cannes Film Festival Award for Best Director$"),
    ("Oscar, Best Actress", r"^Academy Award for Best Actress$"),
    ("Oscar, Best Actor", r"^Academy Award for Best Actor$"),
    ("Oscar, Best Cinematography", r"^Academy Award for Best Cinematography$"),
]
FESTIVAL = {"Palme d'Or", "Golden Lion", "Golden Bear", "Grand Prix, Cannes", "Silver Bear", "Silver Lion",
            "Venice Grand Jury Prize", "Cannes Jury Prize", "Caméra d'Or", "Golden Leopard",
            "Sundance Grand Jury Prize", "Best Director, Cannes"}


def notable(labels: list[str]) -> list[str]:
    """Award labels -> our short names for the notable ones, most prestigious first."""
    out = []
    for name, pat in NOTABLE:
        if any(re.search(pat, lab) for lab in labels) and name not in out:
            out.append(name)
    return out


def query(tmdb_ids: list[int]) -> str:
    values = " ".join(f'"{i}"' for i in tmdb_ids)
    return f"""SELECT ?tmdb ?awardLabel ?spine ?cc WHERE {{
  VALUES ?tmdb {{ {values} }}
  ?f wdt:P4947 ?tmdb .
  OPTIONAL {{ ?f wdt:P166 ?award . ?award rdfs:label ?awardLabel FILTER(lang(?awardLabel) = "en") }}
  OPTIONAL {{ ?f wdt:P12279 ?spine }}
  OPTIONAL {{ ?f wdt:P9584 ?cc }}
}}"""


def _fetch(q: str) -> dict:
    url = SPARQL + "?" + urllib.parse.urlencode({"query": q})
    req = urllib.request.Request(url, headers={"Accept": "application/sparql-results+json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def parse(result: dict, asked: list[int], today: str) -> dict[str, dict]:
    raw: dict[str, dict] = {str(i): {"labels": set(), "spine": None, "cc": False} for i in asked}
    for b in result.get("results", {}).get("bindings", []):
        r = raw.setdefault(b["tmdb"]["value"], {"labels": set(), "spine": None, "cc": False})
        if "awardLabel" in b:
            r["labels"].add(b["awardLabel"]["value"])
        if "spine" in b:
            try:
                r["spine"] = int(float(b["spine"]["value"]))
            except ValueError:
                pass
        if "cc" in b:
            r["cc"] = True
    return {k: {"wins": notable(sorted(r["labels"])), "criterion": r["spine"] or (True if r["cc"] else None),
                "checked": today} for k, r in raw.items()}


def refresh(entries: dict, data: Path, fetch=_fetch, today: dt.date | None = None, log=print) -> dict:
    """Fill data/honors.json for films not checked in REFRESH_DAYS."""
    path = data / "honors.json"
    store = load(data)
    today = today or dt.date.today()
    stale = (today - dt.timedelta(days=REFRESH_DAYS)).isoformat()
    todo = sorted({e["tmdb_id"] for e in entries.values() if e.get("tmdb_id")
                   and store.get(str(e["tmdb_id"]), {}).get("checked", "") < stale})
    done = 0
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        try:
            store.update(parse(fetch(query(batch)), batch, today.isoformat()))
            done += len(batch)
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as e:
            log(f"honors: wikidata failed: {e!r}")
            break
        time.sleep(1)  # be polite to the public endpoint
    path.write_text(json.dumps(store, indent=1, ensure_ascii=False))
    n = sum(1 for v in store.values() if v["wins"] or v["criterion"])
    log(f"honors: checked {done}, {n} of {len(store)} films have a notable award or Criterion")
    return store


def load(data: Path) -> dict:
    path = data / "honors.json"
    try:
        return json.loads(path.read_text()) if path.exists() else {}
    except json.JSONDecodeError:
        return {}


def annotate(cache: dict, store: dict) -> None:
    """Copy honors onto cache entries: entry["honors"] = {"wins": [...], "criterion": ...}."""
    for e in cache.values():
        h = store.get(str(e.get("tmdb_id")))
        if h and (h["wins"] or h["criterion"]):
            e["honors"] = {"wins": h["wins"], "criterion": h["criterion"]}
        else:
            e.pop("honors", None)


def line(e: dict) -> str | None:
    """One short line for a pick: "🏆 Golden Bear · Criterion Collection"."""
    h = e.get("honors")
    if not h:
        return None
    bits = list(h["wins"][:2])
    if h.get("criterion"):
        bits.append("Criterion Collection")
    return "🏆 " + " · ".join(bits) if bits else None


def festival_winner(e: dict) -> bool:
    return any(w in FESTIVAL for w in (e.get("honors") or {}).get("wins", []))
