import unittest

from movie_night.agent import KICKOFF_RE, LIKE_KICKOFF_RE, State, step
from movie_night.picker import plan
from movie_night.search import find_like, find_topics, vocabulary


def film(title, tmdb_id, keywords, genres=("Drama",), rating=4.0, services=("Max",), rent=()):
    return {"title": title, "year": 2000, "on_watchlist": True, "tmdb_id": tmdb_id, "runtime_min": 100,
            "genres": list(genres), "keywords": list(keywords), "letterboxd_rating": rating,
            "trailer_url": None, "availability": {"included": list(services), "rent": list(rent), "buy": []}}


CACHE = {
    "condor": film("Three Days of the Condor", 1, ["cia", "spy", "conspiracy", "new york city"], ("Thriller",)),
    "ipcress": film("The Ipcress File", 2, ["espionage", "brainwashing"], ("Thriller",), 3.7),
    "lives": film("The Lives of Others", 3, ["spy", "east germany", "surveillance"], rating=4.3, services=(),
                  rent=("Prime Video",)),
    "hagazussa": film("Hagazussa", 4, ["folk horror", "rural area", "witch"], ("Horror",), 3.2),
    "worm": film("The Lair of the White Worm", 5, ["folk horror", "human sacrifice", "cult"], ("Horror",), 3.4),
    "heat": film("Heat", 6, ["heist", "los angeles, california", "detective"], ("Crime",), 4.3),
    "noise": film("Paris Story", 7, ["paris, france", "based on novel or book", "cult"], rating=4.6),
    "extra": film("Another Cult Film", 8, ["cult"], ("Horror",), 3.0),
}
WICKER = {"tmdb_id": 16307, "title": "The Wicker Man", "year": 1973, "genres": ["Horror", "Mystery"],
          "keywords": ["folk horror", "human sacrifice", "cult", "rural area", "based on novel or book", "paganism"],
          "related_ids": [4]}


def lookup(title, year=None):
    return WICKER if "wicker" in title.lower() else None


class Parsing(unittest.TestCase):
    def test_find_like(self):
        self.assertEqual(find_like("what's something that would be a lot like wicker man"), ("wicker man", None))
        self.assertEqual(find_like("something like The Wicker Man (1973)?"), ("The Wicker Man", 1973))
        self.assertEqual(find_like("more like Heat, but shorter"), ("Heat", None))
        self.assertIsNone(find_like("I'd like something like that"))
        self.assertIsNone(find_like("I like it"))

    def test_topics_use_synonyms_and_the_lists_own_tags(self):
        v = vocabulary(CACHE)
        self.assertIn("spy", find_topics("Delo, we want to watch some spy movies", v))
        self.assertIn("folk horror", find_topics("folk horror tonight?", v))
        self.assertEqual(find_topics("Delo, something fun tonight", v), {})

    def test_kickoffs(self):
        self.assertTrue(KICKOFF_RE.search("Delo, we want to watch some spy movies"))
        self.assertTrue(KICKOFF_RE.search("hey delo"))
        self.assertTrue(LIKE_KICKOFF_RE.search("what's something that would be a lot like wicker man"))
        self.assertFalse(KICKOFF_RE.search("del taco tonight"))


class Planning(unittest.TestCase):
    def test_spy_prefers_household_services(self):
        p = plan("Delo, we want to watch some spy movies", CACHE, seed=0)
        self.assertEqual(p.note, "Spy")
        self.assertEqual(p.slugs[:2], ["condor", "ipcress"])  # streaming first
        self.assertIn("lives", p.slugs)  # rent fills in when fewer than 3 stream
        self.assertTrue(p.reasons["condor"].startswith("Spy"))

    def test_more_like(self):
        p = plan("something a lot like wicker man", CACHE, seed=0, lookup=lookup)
        self.assertEqual(p.note, "More like The Wicker Man (1973)")
        self.assertEqual(set(p.slugs[:2]), {"worm", "hagazussa"})  # Hagazussa is TMDB-related, Worm shares the most tags
        self.assertNotIn("heat", p.slugs)  # nothing in common
        self.assertNotIn("Based on novel", p.reasons.get("noise", ""))  # generic tags don't count
        self.assertIn("folk horror", p.reasons["worm"])

    def test_unknown_title_falls_back(self):
        p = plan("movie night? something like Zzzqx", CACHE, seed=0, lookup=lookup)
        self.assertTrue(p.note.startswith("I couldn't find"))
        self.assertTrue(p.slugs)


class FakeLinq:
    def __init__(self):
        self.msgs, self.sent, self.n = [], [], 0

    def _add(self, handle, text, is_me=False):
        self.n += 1
        self.msgs.append({"id": f"m{self.n}", "created_at": f"2026-11-10T00:{self.n:02d}:00Z",
                          "from_handle": {"handle": handle, "is_me": is_me},
                          "parts": [{"type": "text", "value": text}]})
        return f"m{self.n}"

    def members(self, chat_id):
        return ["a", "b"]

    def messages(self, chat_id):
        return list(self.msgs)

    def send(self, chat_id, body):
        v = body["message"]["parts"][-1]["value"]
        self.sent.append(v)
        return self._add("me", v, is_me=True)

    def say(self, chat_id, text):
        return self.send(chat_id, {"message": {"parts": [{"type": "text", "value": text}]}})


class AgentKickoff(unittest.TestCase):
    def run_one(self, text):
        linq, state = FakeLinq(), State()
        linq._add("a", text)
        what = step(linq, "chat", state, CACHE, [], seed=0, now=0, lookup=lookup, posters=lambda tmdb_id: None)
        return what, linq.sent

    def test_like_request_without_movie_words(self):
        what, sent = self.run_one("what's something that would be a lot like wicker man")
        self.assertTrue(what.startswith("kickoff"))
        self.assertTrue(sent[0].startswith("🍿 More like The Wicker Man (1973): "))

    def test_casual_like_stays_quiet(self):
        what, sent = self.run_one("I'd want something like a nap honestly")
        self.assertIsNone(what)
        self.assertEqual(sent, [])


if __name__ == "__main__":
    unittest.main()
