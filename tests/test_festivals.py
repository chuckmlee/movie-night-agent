import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from movie_night import festivals, linq_format, quality

DAT = """package Cannes::rurban::2025; # -*- perl -*-
# Le film français 0-4: x2.5
our $DATA = <<'EOF';

COMPETITION

"Sentimental Value" (Joachim Trier) [Competition] Grand Prix

Guy Lodge               https://variety.com/review
Sophia Ciminello  8    https://awardswatch.com/a
Sophia Ciminello  8    https://awardswatch.com/b
#moiree
Mark Asch                6
Jordan Cronk             9
# Screen Daily
Peter Bradshaw           7.5
Justin Chang             9
#letterboxd
fan1                     10
fan2                     10
#bunsen_                 8
#critic.de
Till Kadritzke        5
Sandra Onana

"After (Sirat)" (Oliver Laxe, E) [Competition] Jury Prize + Palm Dog
 was: Sirat
Critic A   4
Critic B   5
Critic C   4
Critic D   5
Critic E   6

"Image and Speech (Le livre d'image)" (Jean-Luc Godard) [Competition] Special Palme d'Or
Critic A   3

"Promised Sky (Promis le ciel)" (Erige Sehiri, Tun) [Un Certain Regard] Jury Prize

"Nobody Rated This" (Someone) [Other]

PREDICTIONS
"Sentimental Value" (Joachim Trier) [Competition]
Critic Z   0
EOF
"""


class Parse(unittest.TestCase):
    def setUp(self):
        self.films = {f["titles"][0]: f for f in festivals.parse(DAT, "Cannes", 2025)}

    def test_critics_mean_without_letterboxd_or_duplicates(self):
        sv = self.films["Sentimental Value"]
        self.assertEqual(sv["n"], 6)  # Ciminello once; no Letterboxd users, no commented-out critic
        self.assertAlmostEqual(sv["critics"], (8 + 6 + 9 + 7.5 + 9 + 5) / 6, places=2)
        self.assertEqual((sv["rank"], sv["of"]), (1, 2))
        self.assertEqual(sv["awards"], ["Grand Prix, Cannes"])

    def test_titles_and_prizes(self):
        sirat = self.films["After"]
        self.assertEqual(sirat["titles"][:2], ["After", "Sirat"])
        self.assertEqual(sirat["director"], "Oliver Laxe")
        self.assertEqual(sirat["awards"], ["Cannes Jury Prize"])
        self.assertEqual(self.films["Image and Speech"]["awards"], [])  # a Special Palme isn't the Palme
        self.assertNotIn("Promised Sky", self.films)  # Un Certain Regard's jury prize, and no scores
        self.assertNotIn("Nobody Rated This", self.films)
        self.assertNotIn("rank", self.films["Image and Speech"])  # one critic is too few


class Match(unittest.TestCase):
    def setUp(self):
        self.idx = festivals.index({"Cannes2025": {"films": festivals.parse(DAT, "Cannes", 2025)}})

    def test_by_title_year_and_director(self):
        hit = festivals.match({"title": "Sirāt", "year": 2025, "directors": ["Óliver Laxe"]}, self.idx)
        self.assertEqual(hit["titles"][0], "After")
        self.assertIsNone(festivals.match({"title": "Sirat", "year": 2025, "directors": ["Other Person"]}, self.idx))
        self.assertIsNone(festivals.match({"title": "Sirat", "year": 2019, "directors": ["Oliver Laxe"]}, self.idx))
        self.assertIsNotNone(festivals.match({"title": "Sentimental Value", "year": 2025}, self.idx))

    def test_annotate_line_and_prizes(self):
        cache = {"sv": {"title": "Sentimental Value", "year": 2025, "directors": ["Joachim Trier"],
                        "honors": {"wins": ["Oscar, Best International Feature"], "criterion": None}},
                 "x": {"title": "Unknown", "year": 2025, "festival": {"stale": True}}}
        festivals.annotate(cache, self.idx)
        sv = cache["sv"]
        self.assertEqual(sv["festival"]["rank"], 1)
        self.assertEqual(sv["honors"]["wins"], ["Grand Prix, Cannes", "Oscar, Best International Feature"])
        self.assertNotIn("festival", cache["x"])
        self.assertEqual(festivals.line(sv), "🎟️ Cannes 2025 critics: #1 of 2 (7.4/10)")
        self.assertEqual(festivals.percentile(sv), 100.0)
        pick = linq_format.pick_from_cache({**sv, "tmdb_id": 1}, reason="Why it fits.")
        self.assertIn("🎟️ Cannes 2025 critics", pick.reason)

    def test_line_only_near_the_top(self):
        self.assertIsNone(festivals.line({"festival": {"name": "Cannes 2025", "rank": 40, "of": 93, "critics": 5.1}}))
        self.assertIsNone(festivals.line({}))


class Refresh(unittest.TestCase):
    def test_old_years_once_recent_weekly(self):
        calls = []

        def fetch(name):
            calls.append(name)
            return DAT if name == "Cannes2025" else None

        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            today = dt.date(2026, 11, 11)
            festivals.refresh(d, fetch=fetch, today=today, log=lambda m: None, pause=0)
            first = len(calls)
            self.assertEqual(first, len(festivals.files(today)))
            festivals.refresh(d, fetch=fetch, today=today + dt.timedelta(days=8), log=lambda m: None, pause=0)
            again = calls[first:]
            self.assertTrue(again and all(n.endswith(("2025", "2026")) for n in again))
            self.assertEqual(festivals.cached_index(d)["sentimental value"][0]["rank"], 1)


class Quality(unittest.TestCase):
    def test_festival_critics_fill_in_for_new_films(self):
        entries = {"a": {"tmdb_id": 1, "letterboxd_rating": 3.0}, "b": {"tmdb_id": 2, "letterboxd_rating": 4.2}}
        q = quality.blend(entries, {}, festival={"tmdb-1": 95.0})
        self.assertEqual(q["tmdb-1"]["sources"], 2)
        self.assertEqual(q["tmdb-1"]["parts"]["critics"], 95.0)
        self.assertEqual(quality.highlight(q["tmdb-1"]), "critics love it, fans split")
        self.assertEqual(q["tmdb-2"]["sources"], 1)


if __name__ == "__main__":
    unittest.main()
