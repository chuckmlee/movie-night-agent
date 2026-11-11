import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from movie_night import quality
from movie_night.picker import choose, parse_hints


def film(tid, lb=None, on=True):
    return {"title": f"F{tid}", "tmdb_id": tid, "letterboxd_rating": lb, "on_watchlist": on, "genres": [f"G{tid}"],
            "runtime_min": 100, "availability": {"included": ["Max"], "rent": [], "buy": []}}


OMDB = {"Response": "True", "imdbRating": "7.8", "imdbVotes": "120,345", "Metascore": "80",
        "Ratings": [{"Source": "Internet Movie Database", "Value": "7.8/10"},
                    {"Source": "Rotten Tomatoes", "Value": "92%"}, {"Source": "Metacritic", "Value": "80/100"}]}


class Parse(unittest.TestCase):
    def test_omdb_fields(self):
        self.assertEqual(quality.parse_omdb(OMDB), {"imdb": 7.8, "imdb_votes": 120345, "rt": 92, "mc": 80})
        self.assertEqual(quality.parse_omdb({"imdbRating": "N/A", "Metascore": "N/A", "Ratings": []}), {})


class Blend(unittest.TestCase):
    def test_percentiles_weights_and_missing_sources(self):
        entries = {"a": film(1, 4.2), "b": film(2, 3.5), "c": film(3, 3.0)}
        ratings = {"tmdb-1": {"imdb": 8.0, "imdb_votes": 9000, "rt": 95, "mc": 85},
                   "tmdb-2": {"imdb": 7.0, "imdb_votes": 9000, "rt": 60, "mc": 50},
                   "tmdb-3": {"imdb": 6.0, "imdb_votes": 100}}  # too few votes; no critics
        q = quality.blend(entries, ratings, {1: {"score": 1.25}})
        self.assertEqual(q["tmdb-1"]["sources"], 4)
        self.assertEqual(q["tmdb-1"]["parts"]["letterboxd"], 100.0)
        self.assertAlmostEqual(q["tmdb-1"]["parts"]["circle"], 55.6, delta=1)
        # Only Letterboxd for film 3: its score is that percentile alone, not dragged down by missing data.
        self.assertEqual(q["tmdb-3"], {"score": 0.0, "sources": 1, "parts": {"letterboxd": 0.0}})
        self.assertGreater(q["tmdb-1"]["score"], q["tmdb-2"]["score"])

    def test_circle_has_diminishing_returns(self):
        one, two, five = (quality.circle_points(s) for s in (1.25, 2.5, 6.25))
        self.assertTrue(50 < one < two < five < 90)
        self.assertEqual(quality.circle_points(-1), 0.0)


class Refresh(unittest.TestCase):
    def test_budget_order_and_stop_on_limit(self):
        with tempfile.TemporaryDirectory() as d:
            data = Path(d)
            (data / "ratings.json").write_text(json.dumps({"tmdb-1": {"imdb_id": "tt1", "fetched": "2026-11-01"}}))
            calls = []

            def fetch(iid, key):
                calls.append(iid)
                return OMDB if len(calls) < 3 else {"Response": "False", "Error": "Request limit reached!"}

            entries = {s: film(i) for i, s in enumerate("abcd", start=1)}
            quality.refresh(entries, data, api_key="k", fetch=fetch, imdb_id=lambda t: f"tt{t}",
                            today=dt.date(2026, 11, 11), log=lambda m: None)
            store = json.loads((data / "ratings.json").read_text())
            self.assertNotIn("tt1", calls)  # fresh enough
            self.assertEqual(store["tmdb-2"]["rt"], 92)
            self.assertEqual(len(calls), 3)  # stopped at the limit
            self.assertNotIn("tmdb-4", store)

    def test_no_key_is_a_no_op(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(quality.refresh({"a": film(1)}, Path(d), api_key="", log=lambda m: None), {})


class Ranking(unittest.TestCase):
    def test_quality_lifts_an_otherwise_equal_fit(self):
        cache = {"a": film(1, 4.0), "b": film(2, 4.0)}
        cache["b"]["quality"], cache["a"]["quality"] = 95.0, 10.0
        taste = {"a": [10.0, ""], "b": [10.0, ""]}
        wins = sum(choose(cache, parse_hints("movie"), n=1, seed=s, taste=taste)[0] == "b" for s in range(40))
        self.assertGreater(wins, 30)


if __name__ == "__main__":
    unittest.main()
