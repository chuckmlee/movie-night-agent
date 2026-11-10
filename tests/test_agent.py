import unittest

from movie_night.agent import State, step
from movie_night.picker import choose, parse_hints

A, B = "+15550000001", "+15550000002"


def film(title, rating, genres, runtime=100, services=("Netflix",), rent=()):
    return {"title": title, "year": 2000, "on_watchlist": True, "tmdb_id": 1, "runtime_min": runtime,
            "genres": list(genres), "letterboxd_rating": rating, "trailer_url": f"https://youtu.be/{title}",
            "availability": {"included": list(services), "rent": list(rent), "buy": []}}


CACHE = {
    "alpha": film("Alpha", 4.5, ["Drama"]),
    "bravo": film("Bravo", 4.4, ["Comedy"], runtime=90),
    "charlie": film("Charlie", 4.3, ["Horror"]),
    "delta": film("Delta", 4.2, ["Comedy"], runtime=150),
    "echo": film("Echo", 4.1, ["Action"], services=(), rent=("Prime Video",)),
    "gone": {**film("Gone", 5.0, ["Drama"]), "on_watchlist": False},
}


class FakeLinq:
    """Stands in for the Linq API: keeps a list of messages and records sends."""

    def __init__(self):
        self.msgs, self.sent, self.n = [], [], 0

    def _add(self, handle, text=None, is_me=False, link=None):
        self.n += 1
        mid = f"m{self.n}"
        part = {"type": "link", "value": link} if link else {"type": "text", "value": text}
        self.msgs.append({"id": mid, "created_at": f"2026-11-10T00:{self.n:02d}:00Z",
                          "from_handle": {"handle": handle, "is_me": is_me}, "parts": [part]})
        return mid

    def human(self, handle, text):
        return self._add(handle, text)

    def members(self, chat_id):
        return [A, B]

    def messages(self, chat_id):
        return list(self.msgs)

    def send(self, chat_id, body):
        part = body["message"]["parts"][0]
        self.sent.append(part["value"])
        return self._add("+1agent", is_me=True, **({"link": part["value"]} if part["type"] == "link" else {"text": part["value"]}))

    def say(self, chat_id, text):
        return self.send(chat_id, {"message": {"parts": [{"type": "text", "value": text}]}})

    def react(self, mid, handle, emoji=None, tapback=None):
        m = next(m for m in self.msgs if m["id"] == mid)
        r = {"type": "custom", "custom_emoji": emoji} if emoji else {"type": tapback}
        r["handle"] = {"handle": handle}
        m["parts"][0].setdefault("reactions", []).append(r)


def pick_msg(linq, state, slug):
    return next(mid for mid, s in state.active["msg_to_slug"].items() if s == slug)


class Tokens(unittest.TestCase):
    def test_clean_token(self):
        from movie_night.agent import clean_token
        for raw in ["abc123", "Bearer abc123", " bearer abc123 ", '"abc123"', "Bearer  abc123\n"]:
            self.assertEqual(clean_token(raw), "abc123", raw)
        self.assertIsNone(clean_token(""))


class Hints(unittest.TestCase):
    def test_parse(self):
        h = parse_hints("movie tonight? something funny, under 2 hours, no horror")
        self.assertEqual((h.max_runtime, h.genres, h.avoid_genres), (120, {"Comedy"}, {"Horror"}))
        self.assertTrue(parse_hints("ok to rent").allow_rent)
        self.assertEqual(parse_hints("something light").avoid_genres, {"War", "Horror"})

    def test_choose_filters(self):
        self.assertEqual(choose(CACHE, parse_hints("short comedy"), seed=0), ["bravo"])
        self.assertNotIn("echo", choose(CACHE, parse_hints(""), seed=0))
        self.assertIn("echo", choose(CACHE, parse_hints("rent is fine"), seed=0))
        self.assertNotIn("gone", choose(CACHE, parse_hints("rent is fine"), seed=0))


class Flow(unittest.TestCase):
    def setUp(self):
        self.linq, self.state, self.history = FakeLinq(), State(), []
        self.linq.human(A, "hey")  # B never texts, only reacts

    def poll(self, now=0.0):
        return step(self.linq, "chat", self.state, CACHE, self.history, seed=0, now=now)

    def test_quiet_until_kickoff(self):
        self.assertIsNone(self.poll())
        self.assertEqual(self.linq.sent, [])

    def test_full_session(self):
        self.linq.human(A, "movie night? nothing scary")
        self.assertTrue(self.poll().startswith("kickoff"))
        self.assertTrue(self.linq.sent[0].startswith("🍿"))
        self.assertNotIn("charlie", self.state.active["films"])
        st = self.state
        self.linq.react(pick_msg(self.linq, st, "alpha"), A, "🥇")
        self.linq.react(pick_msg(self.linq, st, "bravo"), A, "🥈")
        self.linq.react(pick_msg(self.linq, st, "bravo"), B, "🥇")
        self.linq.react(pick_msg(self.linq, st, "alpha"), B, tapback="dislike")
        self.assertIsNone(self.poll(now=10))  # golds in, but people may still add 🥈/🥉
        self.assertIsNone(self.poll(now=60))
        self.assertEqual(self.poll(now=200), "tally: bravo")  # settled; Alpha vetoed
        self.assertIn("🏆 Tonight: Bravo", self.linq.sent[-1])
        self.assertIn("Vetoed: Alpha", self.linq.sent[-1])
        self.assertEqual(self.history[-1]["vetoed_by"], [B])
        self.assertEqual(self.history[-1]["missed_top_pick"], [A])
        self.assertIsNone(self.state.active)

        # Next night: B can't veto, and last night's films are skipped.
        self.linq.human(B, "movie?")
        self.poll()
        self.assertIn("no veto tonight", self.linq.sent[-len(self.state.active["msg_to_slug"]) - 1])
        self.assertTrue(set(self.state.active["films"]).isdisjoint(self.history[-1]["films"]) or
                        len(self.state.active["films"]) < 5)

    def test_kickoff_phrases(self):
        from movie_night.agent import KICKOFF_RE
        for t in ["movie night?", "Movie tonight, something short", "movie?", "movie", "pick us a movie", "🎬"]:
            self.assertTrue(KICKOFF_RE.search(t), t)
        for t in ["great movie!", "that movie was long", "the movie theater"]:
            self.assertFalse(KICKOFF_RE.search(t), t)

    def test_waits_for_member_who_only_reacts(self):
        self.linq.human(A, "movie night?")
        self.poll()
        self.linq.react(pick_msg(self.linq, self.state, "alpha"), A, "🥇")
        self.assertIsNone(self.poll())  # B is in the chat and hasn't voted
        self.linq.react(pick_msg(self.linq, self.state, "bravo"), B, "🥇")
        self.poll(now=1)
        self.assertTrue(self.poll(now=100).startswith("tally"))

    def test_silver_after_gold_counts(self):
        # Replays the second live session: B's 🥈 lands after both 🥇s.
        self.linq.human(A, "movie night?")
        self.poll()
        f = self.state.active["films"]
        self.linq.react(pick_msg(self.linq, self.state, f[0]), B, "🥇")
        self.linq.react(pick_msg(self.linq, self.state, f[1]), A, "🥇")
        self.assertIsNone(self.poll(now=5))
        self.linq.react(pick_msg(self.linq, self.state, f[1]), B, "🥈")
        self.assertIsNone(self.poll(now=40))
        self.assertEqual(self.poll(now=200), f"tally: {f[1]}")  # 3+2 beats 3+0

    def test_all_medals_placed_tallies_at_once(self):
        self.linq.human(A, "movie night?")
        self.poll()
        f = self.state.active["films"]
        for who in (A, B):
            for film_slug, e in zip(f, ["🥇", "🥈", "🥉"]):
                self.linq.react(pick_msg(self.linq, self.state, film_slug), who, e)
        self.assertEqual(self.poll(now=1), f"tally: {f[0]}")

    def test_tally_on_request(self):
        self.linq.human(A, "movie")
        self.poll()
        self.linq.react(pick_msg(self.linq, self.state, "bravo"), A, "🥇")
        self.assertIsNone(self.poll())  # B hasn't voted
        self.linq.human(B, "tally")
        self.assertEqual(self.poll(), "tally: bravo")

    def test_trailer_reactions_count(self):
        self.linq.human(A, "movie")
        self.poll()
        trailer = [mid for mid, s in self.state.active["msg_to_slug"].items() if s == "alpha"][-1]
        self.linq.react(trailer, A, "🥇")
        self.linq.react(trailer, B, "🥇")
        self.poll(now=1)
        self.assertEqual(self.poll(now=100), "tally: alpha")

    def test_new_ask_replaces_unfinished_session(self):
        # Nov 10: a session nobody voted on swallowed three later asks.
        self.linq.human(A, "movie night?")
        self.poll()
        first = self.state.active["kickoff_id"]
        self.linq.react(pick_msg(self.linq, self.state, self.state.active["films"][0]), A, "🥇")
        self.linq.human(A, "Delo movie night, something funny")
        self.assertTrue(self.poll().startswith("kickoff"))
        self.assertNotEqual(self.state.active["kickoff_id"], first)
        self.assertEqual(self.history, [])

    def test_delo_tally_is_not_a_new_ask(self):
        self.linq.human(A, "movie")
        self.poll()
        self.linq.react(pick_msg(self.linq, self.state, "bravo"), A, "🥇")
        self.linq.human(B, "Delo, tally")
        self.assertEqual(self.poll(), "tally: bravo")

    def test_as_good_as_phrasing(self):
        from movie_night.agent import _is_kickoff
        from movie_night.search import find_like
        t = "Delo find some watch ideas that are as good as Memories of a Murder "
        self.assertTrue(_is_kickoff(t))
        self.assertEqual(find_like(t), ("Memories of a Murder", None))
        self.assertTrue(_is_kickoff("Movies like Memories of a Murder"))


if __name__ == "__main__":
    unittest.main()
