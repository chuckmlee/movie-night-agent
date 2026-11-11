import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from movie_night import circle, discover, picker, tmdb

TODAY = dt.date(2026, 11, 20)


def snaps(d: Path, days: dict[str, dict]):
    (d / "availability").mkdir()
    for date, snap in days.items():
        (d / "availability" / f"{date}.json").write_text(json.dumps(snap))


def av(*included):
    return {"included": list(included), "rent": [], "buy": []}


class NewlyStreaming(unittest.TestCase):
    def test_only_claims_new_with_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            snaps(d, {
                "2026-11-01": {"old": av("Netflix"), "fresh": av(), "late": av()},
                "2026-11-10": {"old": av("Netflix"), "fresh": av("Max"), "late": av()},
                "2026-11-20": {"old": av("Netflix"), "fresh": av("Max"), "late": av("Prime Video"),
                               "added": av("Netflix")},
            })
            got = discover.newly_streaming(d, TODAY)
        self.assertEqual(got, {"fresh": {"on": "Max", "since": "2026-11-10"},
                               "late": {"on": "Prime Video", "since": "2026-11-20"}})
        # "old" streamed all along; "added" just joined the watchlist, so there's no evidence either way

    def test_outside_the_window(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            snaps(d, {"2026-10-20": {"f": av()}, "2026-10-25": {"f": av("Max")}, "2026-11-20": {"f": av("Max")}})
            self.assertEqual(discover.newly_streaming(d, TODAY), {})


class Gems(unittest.TestCase):
    def test_loved_and_little_seen(self):
        base = {"quality": 85, "quality_info": {"sources": 3}}
        self.assertEqual(discover.gem({**base, "vote_count": 796}), 85)  # Yi Yi
        self.assertIsNone(discover.gem({**base, "vote_count": 10101}))  # Sicario: too well known
        self.assertIsNone(discover.gem({**base, "vote_count": 12}))  # too few to call it loved
        self.assertIsNone(discover.gem({**base, "vote_count": 800, "quality": 60}))
        self.assertIsNone(discover.gem({"quality": 90, "quality_info": {"sources": 1}, "vote_count": 800}))


class ComingSoon(unittest.TestCase):
    def test_line(self):
        cache = {"a": {"title": "Hamnet", "on_watchlist": True, "digital_release": "2026-11-25", "availability": av()},
                 "b": {"title": "Old", "on_watchlist": True, "digital_release": "2026-10-01", "availability": av()},
                 "c": {"title": "Far", "on_watchlist": True, "digital_release": "2027-01-01", "availability": av()}}
        taste = {"coming_soon": [{"title": "Twin Pick", "digital_release": "2026-11-22", "fans": 2, "twins": ["ann"]}]}
        self.assertEqual(discover.soon_line(cache, taste, TODAY),
                         "📅 Coming to rent soon: Hamnet (Nov 25), Twin Pick (Nov 22)")
        self.assertIsNone(discover.soon_line({}, None, TODAY))


class ReleaseInfo(unittest.TestCase):
    def test_us_digital_date(self):
        d = {"vote_count": 796, "release_dates": {"results": [
            {"iso_3166_1": "FR", "release_dates": [{"type": 4, "release_date": "2001-01-01T00:00:00.000Z"}]},
            {"iso_3166_1": "US", "release_dates": [{"type": 3, "release_date": "2000-10-06T00:00:00.000Z"},
                                                   {"type": 4, "release_date": "2006-05-01T00:00:00.000Z"}]}]}}
        info = tmdb.release_info(d)
        self.assertEqual((info["vote_count"], info["digital_release"]), (796, "2006-05-01"))

    def test_recheck_only_while_upcoming(self):
        self.assertTrue(tmdb.release_due({}, "2026-11-20"))
        self.assertFalse(tmdb.release_due({"release_checked": "2026-11-01", "digital_release": "2026-10-01"},
                                          "2026-11-20"))
        self.assertTrue(tmdb.release_due({"release_checked": "2026-11-01", "digital_release": None}, "2026-11-20"))
        self.assertFalse(tmdb.release_due({"release_checked": "2026-11-18", "digital_release": None}, "2026-11-20"))


class Twins(unittest.TestCase):
    def test_agreement_with_shrinkage(self):
        rated = {s: {"tmdb_id": i, "title": s, "stars": st} for i, (s, st) in
                 enumerate([("Yi Yi", 5.0), ("Burning", 4.5), ("Exotica", 4.5), ("Cats", 1.0)], 1)}
        rev = lambda who, i, stars: {"who": who, "tmdb_id": i, "title": "", "stars": stars}  # noqa: E731
        store = {"reviews": {
            "1": rev("ann", 1, 5.0), "2": rev("ann", 2, 4.5), "3": rev("ann", 3, 4.0), "4": rev("ann", 4, 1.5),
            "5": rev("bob", 1, 5.0),  # one match isn't enough
            "6": rev("cy", 1, 2.0), "7": rev("cy", 2, 2.0), "8": rev("cy", 4, 5.0),  # disagrees
        }}
        t = circle.twins(store, rated)
        self.assertEqual(list(t), ["ann"])
        self.assertEqual(t["ann"]["both_loved"][0], "Yi Yi")
        store["reviews"]["9"] = {"who": "ann", "tmdb_id": 50, "title": "New", "stars": 4.5}
        self.assertEqual(circle.scores(store, t)[50]["twins"], ["ann"])


def entry(title, genre, **kw):
    return {"title": title, "tmdb_id": hash(title) % 10000, "genres": [genre], "runtime_min": 100,
            "availability": av("Netflix"), "on_watchlist": True, **kw}


class Mix(unittest.TestCase):
    def test_slots_and_labels(self):
        cache = {
            "w1": entry("W1", "Drama"), "w2": entry("W2", "Comedy"), "w3": entry("W3", "Horror"),
            "new": entry("New", "Crime", new_on={"on": "Max", "since": "2026-11-12"}),
            "gem": entry("Gem", "Romance", quality=88, quality_info={"sources": 3}, vote_count=900),
            "tmdb-1": entry("Twin", "War", on_watchlist=False, wildcard=True, score=5.0, reason="ann loved it",
                            twins=[{"who": "ann", "weight": 0.6, "both_loved": ["Yi Yi"]}]),
            "tmdb-2": entry("Wild", "Western", on_watchlist=False, wildcard=True, score=9.0),
        }
        scores = {s: [5.0, f"why {s}"] for s in ("w1", "w2", "w3", "new", "gem")}
        p = picker.mix(cache, picker.Hints(), 5, set(), 0, scores)
        self.assertEqual(p.slugs[:3], ["new", "tmdb-1", "gem"])
        self.assertEqual(p.labels["new"], "🆕 New on Max since Nov 12")
        self.assertEqual(p.labels["tmdb-1"], "👯 ann rates like you: you both loved Yi Yi · 🃏 not on your watchlist")
        self.assertEqual(p.labels["gem"], "💎 Hidden gem: loved, little seen")
        self.assertNotIn("tmdb-2", p.slugs)  # the twin took the wildcard slot
        self.assertEqual(p.summary(), "5 picks: 1 new on your services 🆕, 1 from a taste twin 👯, "
                                      "1 hidden gem 💎 and 2 from the watchlist")


if __name__ == "__main__":
    unittest.main()
