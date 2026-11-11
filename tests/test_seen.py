import unittest

from movie_night.agent import State, step
from movie_night.seen import FreshSeen

RSS = """<?xml version="1.0"?><rss xmlns:letterboxd="https://letterboxd.com" xmlns:tmdb="https://themoviedb.org">
<channel><item><guid>g1</guid><letterboxd:filmTitle>Blue Velvet</letterboxd:filmTitle>
<letterboxd:filmYear>1986</letterboxd:filmYear><tmdb:movieId>793</tmdb:movieId>
<letterboxd:memberRating>4.5</letterboxd:memberRating><description>x</description></item></channel></rss>"""
RATED = """<ul><li class="griditem"><div data-item-slug="heat" data-item-name="Heat (1995)"></div></li></ul>"""


class Fresh(unittest.TestCase):
    def make(self, pages):
        calls = []

        def fetch(url):
            calls.append(url)
            return pages[url.split("/")[-2]]

        return FreshSeen("hh", fetch=fetch, log=lambda m: None, clock=lambda: 0), calls

    def test_drops_logged_and_rated_films_but_keeps_open_picks(self):
        seen, calls = self.make({"rss": RSS})
        cache = {"tmdb-793": {"title": "Blue Velvet", "year": 1986, "tmdb_id": 793, "wildcard": True},
                 "heat": {"title": "Heat", "year": 1995, "tmdb_id": 949},
                 "thief": {"title": "Thief", "year": 1981, "tmdb_id": 11524},
                 "carol": {"title": "Carol", "year": 2015, "tmdb_id": 258480}}
        seen.slugs.add("carol")
        seen.slugs.add("heat")
        self.assertEqual(sorted(seen.drop(cache, keep=["carol"])), ["heat", "tmdb-793"])
        self.assertEqual(sorted(cache), ["carol", "thief"])
        seen.drop({})
        self.assertEqual(len(calls), 1)  # cached for 15 minutes

    def test_a_failed_fetch_keeps_working(self):
        import urllib.error

        def fetch(url):
            raise urllib.error.URLError("down")

        seen = FreshSeen("hh", fetch=fetch, log=lambda m: None, clock=lambda: 0)
        cache = {"a": {"title": "A"}}
        self.assertEqual(seen.drop(cache), [])


class NotOfferedTwice(unittest.TestCase):
    def test_unfinished_sessions_count_as_shown(self):
        from tests.test_agent import FakeLinq, A, film
        cache = {f"f{i}": film(f"F{i}", 4.0 + i / 100, [f"G{i}"]) for i in range(12)}
        for i, e in enumerate(cache.values()):
            e["tmdb_id"] = i + 1
        linq, state, history = FakeLinq(), State(), []
        linq.human(A, "movie night?")
        step(linq, "chat", state, cache, history, seed=0, now=0, posters=lambda i: None)
        first = set(state.active["films"])
        linq.human(A, "movie night?")  # a fresh ask, nobody voted on the first
        step(linq, "chat", state, cache, history, seed=0, now=0, posters=lambda i: None)
        self.assertTrue(first.isdisjoint(state.active["films"]))
        self.assertEqual(history, [])

    def test_falls_back_to_shown_films_rather_than_nothing(self):
        from tests.test_agent import FakeLinq, A, film
        cache = {"only": film("Only", 4.0, ["Drama"])}
        linq, state = FakeLinq(), State(shown={"only": "2999-01-01T00:00:00+00:00"})
        linq.human(A, "movie night?")
        self.assertTrue(step(linq, "chat", state, cache, [], seed=0, now=0, posters=lambda i: None).startswith("kickoff"))


if __name__ == "__main__":
    unittest.main()
