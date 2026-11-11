"""What's new, what's coming, and what's quietly great (Chuck, Nov 11).

- New on your services: a watchlist film that started streaming on one of the
  household's services in the last 14 days, read from the daily availability
  snapshots in data/availability/. A film is only "new" if an earlier
  snapshot shows it on the watchlist without that service, so this starts
  working a day after the snapshots begin and never guesses.
- Coming soon: a film whose US digital release (rent/buy, from TMDB) is in the
  next 14 days. There is no free source for "arriving on Netflix next week", so
  the digital date is the honest signal.
- Hidden gem: a film that is loved by consensus (the blended quality score,
  movie_night.quality) but little seen (few TMDB votes). TMDB averages undersell
  these films, so popularity, not TMDB's rating, is what's used from TMDB.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from . import honors as honors_mod

NEW_DAYS = 14
SOON_DAYS = 14
GEM_MAX_VOTES = 4000  # Incendies, the best known of Chuck's examples, has ~3,600; Sicario has ~10,000
GEM_MIN_VOTES = 50  # below this, too few people have seen it to call it loved
GEM_MIN_QUALITY = 70.0  # blended quality, 0-100, from at least two sources
HONORED_QUALITY = 75.0  # stands in for quality when Criterion or a festival prize is all we have


def gem(entry: dict) -> float | None:
    """The film's quality score if it's a hidden gem, else None."""
    q, info, votes = entry.get("quality"), entry.get("quality_info") or {}, entry.get("vote_count")
    if votes is None:
        return None
    h = entry.get("honors") or {}
    if (q is None or info.get("sources", 0) < 2) and (h.get("criterion") or honors_mod.festival_winner(entry)):
        q = HONORED_QUALITY  # few ratings yet, but Criterion or a festival jury vouched for it
    if q is None or (info.get("sources", 0) < 2 and q != HONORED_QUALITY):
        return None
    if not GEM_MIN_VOTES <= votes <= GEM_MAX_VOTES or q < GEM_MIN_QUALITY:
        return None
    return q


def _snapshots(data: Path, since: dt.date) -> list[tuple[str, dict]]:
    out = []
    for f in sorted((data / "availability").glob("*.json")):
        try:
            if dt.date.fromisoformat(f.stem) >= since:
                out.append((f.stem, json.loads(f.read_text())))
        except (ValueError, json.JSONDecodeError):
            continue
    return out


def newly_streaming(data: Path, today: dt.date | None = None, days: int = NEW_DAYS) -> dict[str, dict]:
    """slug -> {"on": service, "since": "YYYY-MM-DD"} for watchlist films that started
    streaming on a household service within `days`."""
    today = today or dt.date.today()
    snaps = _snapshots(data, today - dt.timedelta(days=days + 30))
    if len(snaps) < 2:
        return {}
    cutoff = (today - dt.timedelta(days=days)).isoformat()
    _, latest = snaps[-1]
    out = {}
    for slug, avail in latest.items():
        for service in avail.get("included") or []:
            since = None
            for date, snap in reversed(snaps[:-1]):  # walk back until the service wasn't there
                a = snap.get(slug)
                if a is None:
                    since = None  # wasn't on the watchlist then: can't tell, so don't claim it's new
                    break
                if service not in (a.get("included") or []):
                    break
                since = date
            else:
                continue  # streaming there as far back as we can see
            if a is None:
                continue
            first = since or snaps[-1][0]
            if first >= cutoff and (slug not in out or first > out[slug]["since"]):
                out[slug] = {"on": service, "since": first}
    return out


def coming_soon(entries: list[dict], today: dt.date | None = None, days: int = SOON_DAYS) -> list[dict]:
    """Films not streaming on your services whose digital release is in the next `days`, soonest first."""
    today = today or dt.date.today()
    lo, hi = today.isoformat(), (today + dt.timedelta(days=days)).isoformat()
    out = [e for e in entries if lo < (e.get("digital_release") or "") <= hi
           and not (e.get("availability") or {}).get("included")]
    return sorted(out, key=lambda e: e["digital_release"])


_memo: dict = {}


def annotate(cache: dict, data: Path, today: dt.date | None = None) -> None:
    """Mark watchlist entries that just started streaming: entry["new_on"] = {"on", "since"}.

    Delo polls every few seconds; the snapshots change once a day, so the result is reused
    until today's date or the set of snapshot files changes."""
    files = sorted(f.name for f in (data / "availability").glob("*.json")) if (data / "availability").exists() else []
    key = (str(data), (today or dt.date.today()).isoformat(), tuple(files))
    if _memo.get("key") != key:
        _memo.update(key=key, fresh=newly_streaming(data, today))
    fresh = _memo["fresh"]
    for slug, e in cache.items():
        if slug in fresh and e.get("on_watchlist"):
            e["new_on"] = fresh[slug]
        else:
            e.pop("new_on", None)


def short_date(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{d.strftime('%b')} {d.day}"


def soon_line(cache: dict, taste: dict | None, today: dt.date | None = None, n: int = 2) -> str | None:
    """One intro line: watchlist films and circle favorites with a digital release in the next two weeks."""
    picks = coming_soon([e for e in cache.values() if e.get("on_watchlist")], today)
    wild = sorted((taste or {}).get("coming_soon") or [], key=lambda w: (-len(w.get("twins") or []), -w.get("fans", 0)))
    names, seen = [], set()
    for e in picks[:n] + coming_soon(wild[:5], today):
        if e["title"] in seen or len(names) >= n:
            continue
        seen.add(e["title"])
        names.append(f"{e['title']} ({short_date(e['digital_release'])})")
    return "📅 Coming to rent soon: " + ", ".join(names) if names else None
