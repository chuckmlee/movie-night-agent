import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from movie_night import circle, discover, honors


def b(tmdb, award=None, spine=None, cc=None):
    row = {"tmdb": {"value": str(tmdb)}}
    if award:
        row["awardLabel"] = {"value": award}
    if spine:
        row["spine"] = {"value": str(spine)}
    if cc:
        row["cc"] = {"value": str(cc)}
    return row


RESULT = {"results": {"bindings": [
    b(1, "Golden Bear"), b(1, "Teddy Award"), b(1, "Academy Award for Best International Feature Film"),
    b(2, spine=339, cc=1), b(3, cc=5), b(4, "Saturn Award for Best Science Fiction Film"),
]}}


class Parse(unittest.TestCase):
    def test_notable_wins_and_criterion(self):
        got = honors.parse(RESULT, [1, 2, 3, 4, 5], "2026-11-11")
        self.assertEqual(got["1"]["wins"], ["Golden Bear", "Oscar, Best International Feature"])
        self.assertEqual(got["2"]["criterion"], 339)
        self.assertIs(got["3"]["criterion"], True)
        self.assertEqual(got["4"]["wins"], [])  # not a notable award
        self.assertEqual(got["5"], {"wins": [], "criterion": None, "checked": "2026-11-11"})  # asked, not found

    def test_line(self):
        self.assertEqual(honors.line({"honors": {"wins": ["Golden Bear"], "criterion": 339}}),
                         "🏆 Golden Bear · Criterion Collection")
        self.assertIsNone(honors.line({}))

    def test_refresh_batches_and_caches(self):
        calls = []

        def fetch(q):
            calls.append(q)
            return RESULT

        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            entries = {"a": {"tmdb_id": 1}, "b": {"tmdb_id": 2}}
            honors.refresh(entries, d, fetch=fetch, today=dt.date(2026, 11, 11), log=lambda m: None)
            honors.refresh(entries, d, fetch=fetch, today=dt.date(2026, 11, 20), log=lambda m: None)
            self.assertEqual(len(calls), 1)  # second run: still fresh
            store = json.loads((d / "honors.json").read_text())
        self.assertEqual(store["1"]["wins"][0], "Golden Bear")


class Gem(unittest.TestCase):
    def test_criterion_vouches_when_ratings_are_thin(self):
        e = {"vote_count": 400, "honors": {"wins": [], "criterion": 326}}  # Metropolitan
        self.assertEqual(discover.gem(e), discover.HONORED_QUALITY)
        self.assertIsNone(discover.gem({**e, "vote_count": 9000}))


class Loved(unittest.TestCase):
    def test_phrases_from_fans_most_mentioned_first(self):
        ex = lambda s, loved: {"sentiment": s, "loved": loved, "disliked": [], "quote": None}  # noqa: E731
        store = {"reviews": {
            "1": {"who": "a", "tmdb_id": 9, "title": "X", "stars": 4.5, "extract": ex(0.9, ["The score", "Kinski"])},
            "2": {"who": "b", "tmdb_id": 9, "title": "X", "stars": 4.0, "extract": ex(0.7, ["the score."])},
            "3": {"who": "c", "tmdb_id": 9, "title": "X", "stars": 1.0, "extract": ex(-0.8, ["the poster"])},
        }}
        f = circle.scores(store)[9]
        self.assertEqual(f["loved"], ["the score", "kinski"])  # the hater's praise doesn't count
        self.assertEqual(circle.loved_line(f), "❤️ Loved for: the score, kinski")


if __name__ == "__main__":
    unittest.main()
