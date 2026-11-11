import unittest

from movie_night import search, tmdb
from movie_night.picker import plan


def film(title, directors=(), cast=(), rating=4.0, kws=()):
    return {"title": title, "year": 1990, "on_watchlist": True, "tmdb_id": abs(hash(title)) % 10**6,
            "runtime_min": 110, "genres": ["Drama"], "keywords": list(kws), "letterboxd_rating": rating,
            "directors": list(directors), "cast": list(cast),
            "availability": {"included": ["Max"], "rent": [], "buy": []}}


CACHE = {
    "fwwm": film("Twin Peaks: Fire Walk with Me", ["David Lynch"], ["Sheryl Lee", "Ray Wise"]),
    "blue-velvet": film("Blue Velvet", ["David Lynch"], ["Kyle MacLachlan", "Laura Dern"], 4.1),
    "carol": film("Carol", ["Todd Haynes"], ["Cate Blanchett", "Rooney Mara"], 3.9),
    "tar": film("Tár", ["Todd Field"], ["Cate Blanchett"], 3.8),
    "ida": film("Ida", ["Paweł Pawlikowski"], ["Agata Kulesza"], 4.0),
}


class Credits(unittest.TestCase):
    def test_people_from_tmdb_details(self):
        d = {"original_language": "ko",
             "spoken_languages": [{"iso_639_1": "ko", "english_name": "Korean"}],
             "production_countries": [{"name": "South Korea"}],
             "credits": {"crew": [{"job": "Director", "name": "Bong Joon Ho"}, {"job": "Writer", "name": "X"}],
                         "cast": [{"name": f"A{i}", "order": i} for i in range(8, 0, -1)]}}
        self.assertEqual(tmdb.people(d), {"directors": ["Bong Joon Ho"], "cast": ["A1", "A2", "A3", "A4", "A5"],
                                          "countries": ["South Korea"], "language": "Korean"})


class Names(unittest.TestCase):
    def test_find_wanted_and_avoided(self):
        self.assertEqual(search.find_people("lynch movies tonight", CACHE), (["David Lynch"], []))
        self.assertEqual(search.find_people("something with Cate Blanchett", CACHE), (["Cate Blanchett"], []))
        self.assertEqual(search.find_people("Delo veto fire walk with me, no David lynch tonight", CACHE),
                         ([], ["David Lynch"]))
        # "Todd" alone is two people, and "with me" isn't a name.
        self.assertEqual(search.find_people("todd movie", CACHE), ([], []))

    def test_plain_ask_by_director(self):
        p = plan("movie night, lynch movies", CACHE, seed=1)
        self.assertEqual(sorted(p.slugs), ["blue-velvet", "fwwm"])
        self.assertEqual(p.reasons["fwwm"], "Directed by David Lynch")
        self.assertEqual(p.note, "David Lynch")

    def test_by_actor(self):
        p = plan("movie night? something with cate blanchett", CACHE, seed=1)
        self.assertEqual(sorted(p.slugs), ["carol", "tar"])
        self.assertEqual(p.reasons["tar"], "With Cate Blanchett")

    def test_no_director_excludes_their_films(self):
        p = plan("movie night, no david lynch tonight", CACHE, seed=1)
        self.assertTrue(p.slugs)
        self.assertNotIn("fwwm", p.slugs)
        self.assertNotIn("blue-velvet", p.slugs)

    def test_claude_sees_credits(self):
        from movie_night.ask import _line
        line = _line("fwwm", CACHE["fwwm"])
        self.assertIn('"director": ["David Lynch"]', line)
        self.assertIn('"cast": ["Sheryl Lee", "Ray Wise"]', line)


if __name__ == "__main__":
    unittest.main()
