import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from movie_night import sync
from movie_night.watchlist import FilmPage, WatchlistFilm


class MissingFromTmdb(unittest.TestCase):
    def test_a_dropped_id_is_not_retried_every_morning(self):
        calls = []

        def enrich(tmdb_id):
            calls.append(tmdb_id)
            raise urllib.error.HTTPError("u", 404, "Not Found", {}, None)

        films = [WatchlistFilm("dekalog", "Dekalog", 1989, None, "u")]
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(sync, "read_watchlist", return_value=films), \
                mock.patch.object(sync, "read_film_page", return_value=FilmPage(343824, "movie", 4.6, 100)), \
                mock.patch.object(sync.tmdb, "enrich", side_effect=enrich), \
                mock.patch.object(sync.tmdb, "_get", side_effect=AssertionError("no availability lookup")), \
                mock.patch.object(sync, "LETTERBOXD_DELAY", 0):
            d = Path(d)
            first = sync.sync("x", d, log=lambda m: None)
            again = sync.sync("x", d, log=lambda m: None)
            entry = json.loads((d / "films.json").read_text())["dekalog"]
        self.assertEqual(calls, [343824])
        self.assertEqual((first["tmdb_missing"], first["enrich_failed"], again["tmdb_missing"]), (1, 0, 1))
        self.assertIn("tmdb_missing", entry)


if __name__ == "__main__":
    unittest.main()
