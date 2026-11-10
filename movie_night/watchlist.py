"""Read a public Letterboxd watchlist.

Reads only the household's own public list, at low volume (one page per
second, once a day), with an honest user agent. Letterboxd has no public API
for this, so if the page layout changes the parser fails loudly rather than
returning a silently short list.
"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.request
from dataclasses import asdict, dataclass

USER_AGENT = "movie-night-agent/0.1 (personal household project)"
ITEM_RE = re.compile(r"<div[^>]*data-component-class=\"LazyPoster\"[^>]*>", re.S)
ATTR_RE = re.compile(r'([\w-]+)=(?:"([^"]*)"|\'([^\']*)\')')
PAGE_RE = re.compile(r"/watchlist/page/(\d+)/")
YEAR_RE = re.compile(r"^(.*) \((\d{4})\)$")


@dataclass
class WatchlistFilm:
    slug: str
    title: str
    year: int | None
    letterboxd_id: str | None  # e.g. "film:1315318"
    url: str


def parse_page(page_html: str) -> tuple[list[WatchlistFilm], int]:
    """Return the films on one page and the highest page number linked."""
    films = []
    for tag in ITEM_RE.findall(page_html):
        attrs = {m[0]: html.unescape(m[1] or m[2]) for m in ATTR_RE.findall(tag)}
        slug = attrs.get("data-item-slug")
        if not slug:
            continue
        name = attrs.get("data-item-name", slug)
        m = YEAR_RE.match(name)
        title, year = (m.group(1), int(m.group(2))) if m else (name, None)
        lb_id = None
        try:
            lb_id = json.loads(attrs.get("data-postered-identifier", "{}")).get("uid")
        except json.JSONDecodeError:
            pass
        films.append(WatchlistFilm(slug, title, year, lb_id, f"https://letterboxd.com/film/{slug}/"))
    pages = [int(p) for p in PAGE_RE.findall(page_html)]
    return films, max(pages, default=1)


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def read_watchlist(username: str, delay: float = 1.0, max_pages: int | None = None) -> list[WatchlistFilm]:
    base = f"https://letterboxd.com/{username}/watchlist/"
    first, last_page = parse_page(fetch(base))
    if not first:
        raise RuntimeError("watchlist page parsed to zero films; the page layout may have changed")
    films = list(first)
    if max_pages:
        last_page = min(last_page, max_pages)
    for n in range(2, last_page + 1):
        time.sleep(delay)
        page, _ = parse_page(fetch(f"{base}page/{n}/"))
        if not page:
            raise RuntimeError(f"page {n} parsed to zero films")
        films.extend(page)
    seen, unique = set(), []
    for f in films:
        if f.slug not in seen:
            seen.add(f.slug)
            unique.append(f)
    return unique


TMDB_RE = re.compile(r'data-tmdb-type="(\w+)"\s+data-tmdb-id="(\d+)"')
RATING_RE = re.compile(r'"ratingValue":\s*([0-9.]+)')
RATING_COUNT_RE = re.compile(r'"ratingCount":\s*(\d+)')


@dataclass
class FilmPage:
    tmdb_id: int | None
    tmdb_type: str | None  # "movie" or "tv"
    rating: float | None  # Letterboxd average, out of 5
    rating_count: int | None


def parse_film_page(page_html: str) -> FilmPage:
    m = TMDB_RE.search(page_html)
    r = RATING_RE.search(page_html)
    c = RATING_COUNT_RE.search(page_html)
    return FilmPage(
        int(m.group(2)) if m else None,
        m.group(1) if m else None,
        float(r.group(1)) if r else None,
        int(c.group(1)) if c else None,
    )


def read_film_page(slug: str) -> FilmPage:
    return parse_film_page(fetch(f"https://letterboxd.com/film/{slug}/"))


if __name__ == "__main__":
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="Dump a public Letterboxd watchlist as JSON lines")
    ap.add_argument("username")
    ap.add_argument("--max-pages", type=int)
    args = ap.parse_args()
    for film in read_watchlist(args.username, max_pages=args.max_pages):
        sys.stdout.write(json.dumps(asdict(film)) + "\n")
