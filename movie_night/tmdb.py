"""TMDB enrichment: runtime, genres, trailer and US availability for one film.

Auth is the TMDB API Read Access Token as a Bearer header. In the cloud
session the proxy injects it for api.themoviedb.org; elsewhere set TMDB_TOKEN.
Availability data on TMDB comes from JustWatch, so it is a daily snapshot,
not a live check.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

BASE = "https://api.themoviedb.org/3"

# The household's subscriptions, as TMDB US provider ids (checked Nov 10, 2026).
# Ad tiers and kids profiles count as the same subscription.
SUBSCRIPTIONS: dict[str, set[int]] = {
    "Netflix": {8, 175, 1796},
    "Max": {1899},
    "Prime Video": {9, 613, 2100},
    "Apple TV": {350},
    "Peacock": {386, 387},
    "YouTube Premium": {188},
}
# Where renting is easiest from the TV, in order of preference.
RENT_STORES: dict[int, str] = {10: "Prime Video", 2: "Apple TV", 192: "YouTube"}


@dataclass
class Availability:
    included: list[str] = field(default_factory=list)  # household services it streams on
    rent: list[str] = field(default_factory=list)
    buy: list[str] = field(default_factory=list)

    def where(self) -> str | None:
        """One short phrase for the pick message."""
        if self.included:
            return "On " + " and ".join(self.included[:2])
        if self.rent:
            return "Rent on " + self.rent[0]
        if self.buy:
            return "Buy on " + self.buy[0]
        return None


@dataclass
class Enrichment:
    tmdb_id: int
    runtime_min: int | None
    genres: list[str]
    trailer_url: str | None
    overview: str
    availability: Availability


def _get(path: str, **params) -> dict:
    url = f"{BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    token = os.environ.get("TMDB_TOKEN") or "injected-by-proxy"
    req = urllib.request.Request(url, headers={"Accept": "application/json", "Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def pick_trailer(videos: list[dict]) -> str | None:
    """The main official English YouTube trailer: earliest published, teasers last."""
    cands = [v for v in videos if v.get("site") == "YouTube" and v.get("type") == "Trailer"]
    if not cands:
        return None

    def rank(v):
        return (
            not v.get("official", False),
            v.get("iso_639_1") != "en",
            "teaser" in (v.get("name") or "").lower(),
            v.get("published_at") or "",
        )

    return f"https://www.youtube.com/watch?v={min(cands, key=rank)['key']}"


def parse_availability(us: dict | None) -> Availability:
    us = us or {}
    included = []
    flat_ids = {p["provider_id"] for p in us.get("flatrate", []) + us.get("free", []) + us.get("ads", [])}
    for name, ids in SUBSCRIPTIONS.items():
        if flat_ids & ids:
            included.append(name)

    def stores(kind):
        ids = {p["provider_id"] for p in us.get(kind, [])}
        return [name for pid, name in RENT_STORES.items() if pid in ids]

    return Availability(included, stores("rent"), stores("buy"))


def parse_details(d: dict) -> Enrichment:
    return Enrichment(
        tmdb_id=d["id"],
        runtime_min=d.get("runtime") or None,
        genres=[g["name"] for g in d.get("genres", [])],
        trailer_url=pick_trailer((d.get("videos") or {}).get("results", [])),
        overview=d.get("overview") or "",
        availability=parse_availability(((d.get("watch/providers") or {}).get("results") or {}).get("US")),
    )


def enrich(tmdb_id: int) -> Enrichment:
    return parse_details(_get(f"/movie/{tmdb_id}", append_to_response="videos,watch/providers"))


def search_id(title: str, year: int | None) -> int | None:
    """Fallback when the Letterboxd page gives no TMDB id."""
    params = {"query": title}
    if year:
        params["year"] = year
    results = _get("/search/movie", **params).get("results", [])
    return results[0]["id"] if results else None
