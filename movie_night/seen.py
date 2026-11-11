"""Films the household has just watched or rated, so Delo stops offering them the same day.

The taste profile only learns new ratings at the 5 AM rebuild. Until then, a
wildcard you rated an hour ago kept coming back (Blue Velvet, Nov 11). This
reads two cheap, public pages at most every 15 minutes:

- the diary RSS feed (the latest ~50 logs, with TMDB ids), and
- the first page of films sorted by rating date (ratings made without a log).

Both are fetched with the honest user agent in watchlist.fetch. A failure just
keeps what was read last time.
"""

from __future__ import annotations

import time
import urllib.error
import xml.etree.ElementTree as ET

from .circle import parse_feed
from .taste import parse_films_page
from .watchlist import fetch as lb_fetch

EVERY_SECONDS = 15 * 60


def _key(title: str | None, year) -> tuple[str, int | None]:
    return ((title or "").strip().lower(), int(year) if year else None)


class FreshSeen:
    def __init__(self, username: str, fetch=lb_fetch, log=print, every: float = EVERY_SECONDS, clock=time.time):
        self.user, self.fetch, self.log, self.every, self.clock = username, fetch, log, every, clock
        self.ids: set[int] = set()
        self.titles: set[tuple[str, int | None]] = set()
        self.slugs: set[str] = set()
        self.checked = None

    def refresh(self) -> None:
        if self.checked is not None and self.clock() - self.checked < self.every:
            return
        self.checked = self.clock()
        try:
            for item in parse_feed(self.fetch(f"https://letterboxd.com/{self.user}/rss/"), self.user):
                self.ids.add(item["tmdb_id"])
                self.titles.add(_key(item["title"], item["year"]))
        except (urllib.error.URLError, ET.ParseError, ValueError) as e:
            self.log(f"seen: diary feed failed: {e!r}")
        try:
            films, _ = parse_films_page(self.fetch(f"https://letterboxd.com/{self.user}/films/by/rated-date/"))
            for f in films:
                self.slugs.add(f.slug)
                self.titles.add(_key(f.title, f.year))
        except (urllib.error.URLError, ValueError, AttributeError) as e:
            self.log(f"seen: rated films page failed: {e!r}")

    def drop(self, cache: dict, keep=()) -> list[str]:
        """Remove films just watched or rated from this poll's cache, except `keep` (the open
        session's picks, which the tally still needs). Returns what was dropped."""
        self.refresh()
        gone = [s for s, e in cache.items() if s not in keep and (s in self.slugs or e.get("tmdb_id") in self.ids or _key(e.get("title"), e.get("year")) in self.titles)]
        for s in gone:
            del cache[s]
        return gone
