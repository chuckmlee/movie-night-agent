import unittest
from pathlib import Path

from movie_night.taste import build_profile, parse_films_page, rank, reason, score, weight


def item(slug, name, rated=None, liked=False):
    r = f'<span class="rating -micro -darker rated-{rated}">★</span>' if rated else ""
    h = '<span class="like liked-micro has-icon icon-liked icon-16"></span>' if liked else ""
    return (f'<li class="griditem"><div class="react-component" data-component-class="LazyPoster" '
            f'data-item-name="{name}" data-item-slug="{slug}"></div>'
            f'<p class="poster-viewingdata">{r}{h}</p></li>')


PAGE = ("<ul>" + item("conclave", "Conclave (2024)", 8, liked=True) + item("cats", "Cats (2019)", 2)
        + item("unrated", "Unrated (2001)") + '</ul><a href="/chucklee/films/page/6/">6</a>')

RATED = {
    "zodiac": {"slug": "zodiac", "title": "Zodiac", "stars": 5.0, "liked": True, "tmdb_id": 1,
               "keywords": ["serial killer", "detective", "journalist"], "genres": ["Crime", "Thriller"], "rec_ids": [10]},
    "seven": {"slug": "seven", "title": "Se7en", "stars": 4.5, "liked": False, "tmdb_id": 2,
              "keywords": ["serial killer", "detective", "rain"], "genres": ["Crime"], "rec_ids": [10, 11]},
    "cats": {"slug": "cats", "title": "Cats", "stars": 1.0, "liked": False, "tmdb_id": 3,
             "keywords": ["musical", "cat"], "genres": ["Comedy", "Music"], "rec_ids": [12]},
}
CACHE = {
    "memories": {"title": "Memories of Murder", "on_watchlist": True, "tmdb_id": 10,
                 "keywords": ["serial killer", "detective", "rural"], "genres": ["Crime", "Thriller"]},
    "musical": {"title": "Some Musical", "on_watchlist": True, "tmdb_id": 12,
                "keywords": ["musical"], "genres": ["Music", "Comedy"]},
    "seen": {"title": "Se7en", "on_watchlist": True, "tmdb_id": 2, "keywords": ["serial killer"], "genres": ["Crime"]},
    "off": {"title": "Off list", "on_watchlist": False, "tmdb_id": 99, "keywords": [], "genres": []},
}


class Parse(unittest.TestCase):
    def test_films_page(self):
        films, last = parse_films_page(PAGE)
        self.assertEqual(last, 6)
        self.assertEqual([(f.slug, f.year, f.stars, f.liked) for f in films],
                         [("conclave", 2024, 4.0, True), ("cats", 2019, 1.0, False), ("unrated", 2001, None, False)])


class Profile(unittest.TestCase):
    def test_weight(self):
        self.assertEqual(weight(5, False), 1.0)
        self.assertEqual(weight(3, False), 0.0)
        self.assertEqual(weight(None, True), 0.5)
        self.assertLess(weight(1, False), 0)

    def test_rank_prefers_what_you_love(self):
        p = build_profile(RATED)
        ranked = rank(CACHE, p)
        self.assertEqual([s.slug for s in ranked], ["memories", "musical"])  # off-list and already-rated films left out
        self.assertEqual(ranked[0].parts["recommended_by"], ["zodiac", "seven"])
        self.assertLess(ranked[1].score, 0)  # Cats was 1 star; its recommendation doesn't count

    def test_reason_names_loved_films(self):
        p = build_profile(RATED)
        s, parts = score(CACHE["memories"], p)
        r = reason(CACHE["memories"], p, parts)
        self.assertTrue(r.startswith("Like Zodiac (5★) and Se7en (4.5★)"), r)
        self.assertIn("serial killer", r)


    def test_circle_boosts_and_speaks(self):
        from movie_night.taste import Scored, pick_reason
        p = build_profile(RATED)
        before, _ = score(CACHE["musical"], p)
        p.circle = {12: {"score": 2.0, "people": [{"who": "ann", "signal": 1.0}, {"who": "bob", "signal": 1.0}],
                         "best": {"who": "ann", "signal": 1.0, "quote": "Pure joy.", "stars": 5.0}}}
        after, parts = score(CACHE["musical"], p)
        self.assertGreater(after, before)
        r = pick_reason(Scored("musical", after, reason(CACHE["musical"], p, parts), parts), CACHE["musical"], p)
        self.assertIn("💬 ann (5★) and 1 more you follow: “Pure joy.”", r)


class CircleWildcards(unittest.TestCase):
    """Wildcards come only from films someone in the circle loved, most-agreed-on first."""

    def setUp(self):
        from movie_night.taste import agreement, wildcards
        self.agreement, self.wildcards = agreement, wildcards
        self.p = build_profile(RATED)
        fan = lambda *who: {"score": float(len(who)), "fans": list(who), "people": [], "best": None}  # noqa: E731
        self.p.circle = {
            20: fan("ann"), 21: fan("ann", "bob", "cy"), 22: fan(),  # 22: watched, nobody loved it
            2: fan("ann", "bob"),  # Se7en: the household already rated it
            23: fan("dee"), 24: fan("ann", "bob"),  # 23: obscure, one fan; 24: a short
        }
        base = {"keywords": [], "genres": ["Drama"], "runtime_min": 100, "vote_count": 400, "year": 1990}
        self.store = {"20": {**base, "tmdb_id": 20}, "21": {**base, "tmdb_id": 21}, "22": {**base, "tmdb_id": 22},
                      "23": {**base, "tmdb_id": 23, "vote_count": 12},
                      "24": {**base, "tmdb_id": 24, "runtime_min": 14}}

    def test_only_circle_loved_unseen_features(self):
        wild = self.wildcards(CACHE, self.p, self.store, log=lambda m: None)
        self.assertEqual([w.slug for w in wild], ["21", "20"])  # three fans beat one
        self.assertEqual(wild[0].parts["fans"], 3)

    def test_recommendations_alone_dont_make_a_wildcard(self):
        self.p.circle = {}
        self.assertEqual(self.wildcards(CACHE, self.p, self.store, log=lambda m: None), [])

    def test_lookups_are_budgeted_and_cached(self):
        calls = []
        import movie_night.taste as t
        real, t._details = t._details, lambda rid: calls.append(rid) or {"tmdb_id": rid, "runtime_min": 90,
                                                                         "vote_count": 500, "keywords": [], "genres": []}
        try:
            store = {}
            self.wildcards(CACHE, self.p, store, lookups=2, log=lambda m: None)
            self.assertEqual(calls, [21, 24])  # most fans first; the rest wait for tomorrow
        finally:
            t._details = real

    def test_build_keeps_only_watchable(self):
        import json, tempfile
        import movie_night.circle as c
        import movie_night.taste as t
        from movie_night import tmdb
        streams = {"results": {"US": {"flatrate": [{"provider_id": 8, "provider_name": "Netflix"}]}}}
        real = (tmdb._get, c.scores, c.load)
        tmdb._get = lambda path, **kw: streams if "/21/" in path else {"results": {}}
        c.scores, c.load = (lambda store: self.p.circle), (lambda data: {})
        try:
            with tempfile.TemporaryDirectory() as d:
                d = Path(d)
                (d / "films.json").write_text(json.dumps(CACHE))
                (d / "rated.json").write_text(json.dumps(RATED))
                (d / "wildcards.json").write_text(json.dumps(self.store))
                out = t.build("x", d, refresh=False, log=lambda m: None)
            self.assertEqual(list(out["wildcards"]), ["tmdb-21"])  # 20 isn't streaming or rentable
        finally:
            tmdb._get, c.scores, c.load = real

    def test_diminishing_returns(self):
        one, two, five = self.agreement(1), self.agreement(2), self.agreement(5)
        self.assertLess(two - one, one)
        self.assertLess(five, 17)


if __name__ == "__main__":
    unittest.main()
