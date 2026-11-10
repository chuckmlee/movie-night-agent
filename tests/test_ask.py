import json
import unittest
from types import SimpleNamespace

from movie_night.ask import Asker, is_nuanced
from movie_night.picker import plan


def film(title, kws, rating=4.0, watchlist=True, overview=""):
    return {"title": title, "year": 1990, "on_watchlist": watchlist, "tmdb_id": abs(hash(title)) % 10**6,
            "runtime_min": 110, "genres": ["Drama"], "keywords": kws, "letterboxd_rating": rating,
            "overview": overview, "availability": {"included": ["Max"], "rent": [], "buy": []}}


CACHE = {
    "mother-joan": film("Mother Joan of the Angels", ["nun", "possession", "convent"]),
    "silence": film("Silence", ["priest", "faith", "persecution"]),
    "ken-park": film("Shock Fest", ["nun", "gore"]),
    "heat": film("Heat", ["heist"]),
    "tmdb-9": {**film("The Name of the Rose", ["monastery", "murder"], watchlist=False), "wildcard": True, "score": 9.0},
}
DEVILS = {"tmdb_id": 1, "title": "The Devils", "year": 1971, "genres": ["Drama"],
          "keywords": ["nun", "possession", "priest", "convent"], "overview": "Hysteria in a French town.", "related_ids": []}


class FakeClient:
    def __init__(self, picks, stop="end_turn"):
        self.picks, self.stop, self.prompts = picks, stop, []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.prompts.append(kw["messages"][0]["content"])
        body = {"note": "Like The Devils, less shocking", "picks": [{"id": i, "why": w} for i, w in self.picks]}
        return SimpleNamespace(stop_reason=self.stop, content=[SimpleNamespace(type="text", text=json.dumps(body))])


ASK = "Something like The Devils but less shocking, as intellectually rich"


class Nuance(unittest.TestCase):
    def test_detects_texture_not_topics(self):
        self.assertTrue(is_nuanced(ASK))
        self.assertTrue(is_nuanced("something funny but short"))
        for t in ["movie night?", "spy movies tonight", "something like Heat", "movie night? something fun"]:
            self.assertFalse(is_nuanced(t), t)


class ClaudeChooses(unittest.TestCase):
    def run_plan(self, client):
        return plan(ASK, CACHE, lookup=lambda t, y: DEVILS, ask=Asker(client, log=lambda m: None))

    def test_picks_reasons_note_and_labels(self):
        client = FakeClient([("mother-joan", "Same possessed convent, far less graphic"),
                             ("tmdb-9", "Monastery mystery with real ideas"), ("nope", "not a candidate")])
        p = self.run_plan(client)
        self.assertEqual(p.slugs, ["mother-joan", "tmdb-9"])  # unknown id dropped
        self.assertEqual(p.note, "Like The Devils, less shocking")
        self.assertEqual(p.wildcards, ["tmdb-9"])
        self.assertTrue(p.reasons["mother-joan"].startswith("Same possessed convent, far less graphic · ★ 4.0"))
        prompt = client.prompts[0]
        self.assertIn("Hysteria in a French town.", prompt)  # the named film is described
        self.assertNotIn('"title": "The Devils", "year": 1990', prompt)

    def test_falls_back_to_keywords_when_claude_fails(self):
        p = self.run_plan(FakeClient([], stop="refusal"))
        self.assertTrue(p.note.startswith("More like The Devils"))
        self.assertIn("mother-joan", p.slugs)

    def test_like_title_stops_at_the_qualifier(self):
        from movie_night.search import find_like
        self.assertEqual(find_like(ASK), ("The Devils", None))

    def test_follow_up_goes_to_claude_without_a_tone_word(self):
        client = FakeClient([("silence", "Faith under pressure")])
        p = plan(ASK + "\nFollow-up: limit to catholic themes", CACHE, lookup=lambda t, y: DEVILS,
                 ask=Asker(client, log=lambda m: None), refine=True)
        self.assertEqual(p.slugs, ["silence"])
        self.assertIn("Follow-up: limit to catholic themes", client.prompts[0])

    def test_plain_ask_never_calls_claude(self):
        client = FakeClient([("heat", "x")])
        plan("movie night?", CACHE, ask=Asker(client, log=lambda m: None))
        self.assertEqual(client.prompts, [])


if __name__ == "__main__":
    unittest.main()
