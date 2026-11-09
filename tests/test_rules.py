import unittest

from movie_night.rules import Film, History, Reaction, ReactionEvent, Session

G, S, B, V = Reaction.GOLD, Reaction.SILVER, Reaction.BRONZE, Reaction.VETO
FILMS = [Film("a", "Alpha", 3.9), Film("b", "Bravo", 3.5), Film("c", "Charlie", 4.1), Film("d", "Delta", 3.0)]


def run(events, history=None, films=FILMS):
    s = Session(films, ["chuck", "partner"], history)
    for person, fid, r, *rest in events:
        s.apply(ReactionEvent(person, fid, r, removed=bool(rest and rest[0])))
    return s.tally()


class RulesTest(unittest.TestCase):
    def test_highest_total_wins(self):
        r = run([("chuck", "a", G), ("chuck", "b", S), ("partner", "a", S), ("partner", "b", B)])
        self.assertEqual(r.winner.film_id, "a")
        self.assertIsNone(r.tie_break)

    def test_veto_removes_film(self):
        r = run([("chuck", "a", G), ("partner", "a", V), ("partner", "b", G)])
        self.assertEqual(r.winner.film_id, "b")
        self.assertEqual(r.scores[-1].film.film_id, "a")

    def test_second_gold_moves_the_first(self):
        r = run([("chuck", "a", G), ("chuck", "b", G)])
        self.assertEqual(r.winner.film_id, "b")
        a = next(s for s in r.scores if s.film.film_id == "a")
        self.assertEqual(a.total, 0)

    def test_one_veto_per_person(self):
        r = run([("chuck", "a", V), ("chuck", "b", V), ("partner", "a", G)])
        self.assertEqual(r.winner.film_id, "a")  # veto moved from a to b

    def test_no_back_to_back_veto(self):
        h = History(vetoed_last_session={"partner"})
        r = run([("chuck", "a", G), ("partner", "a", V)], history=h)
        self.assertEqual(r.winner.film_id, "a")
        self.assertEqual(len(r.rejected), 1)

    def test_tie_break_lower_score(self):
        # a: 3+1 = 4, b: 2+2 = 4 -> b wins
        r = run([("chuck", "a", G), ("partner", "a", B), ("chuck", "b", S), ("partner", "b", S)])
        self.assertEqual(r.winner.film_id, "b")
        self.assertIn("tie-break 1", r.tie_break)

    def test_tie_break_missed_top_pick(self):
        # a: chuck 3 + partner 2 = 5 (min 2); c: chuck 2 + partner 3 = 5 (min 2)
        events = [("chuck", "a", G), ("partner", "a", S), ("chuck", "c", S), ("partner", "c", G)]
        r = run(events, history=History(missed_top_pick_last_session={"chuck"}))
        self.assertEqual(r.winner.film_id, "a")
        self.assertIn("tie-break 2", r.tie_break)

    def test_tie_break_rating(self):
        events = [("chuck", "a", G), ("partner", "a", S), ("chuck", "c", S), ("partner", "c", G)]
        r = run(events)
        self.assertEqual(r.winner.film_id, "c")  # 4.1 beats 3.9
        self.assertIn("tie-break 3", r.tie_break)

    def test_everything_vetoed(self):
        two = FILMS[:2]
        r = run([("chuck", "a", V), ("partner", "b", V)], films=two)
        self.assertIsNone(r.winner)
        self.assertTrue(r.all_vetoed)

    def test_removed_reaction_stops_counting(self):
        r = run([("chuck", "a", G), ("chuck", "b", S), ("chuck", "a", G, True)])
        self.assertEqual(r.winner.film_id, "b")

    def test_new_reaction_on_same_film_replaces_old(self):
        r = run([("chuck", "a", G), ("chuck", "a", V), ("partner", "b", B)])
        self.assertEqual(r.winner.film_id, "b")

    def test_unknown_film_rejected(self):
        r = run([("chuck", "zzz", G)])
        self.assertEqual(r.rejected[0][1], "film is not in this session")


if __name__ == "__main__":
    unittest.main()
