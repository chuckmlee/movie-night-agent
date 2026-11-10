import unittest

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


if __name__ == "__main__":
    unittest.main()
