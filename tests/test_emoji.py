import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from movie_night.emoji import Emojis, fallback


class FakeClient:
    def __init__(self, reply):
        self.reply, self.calls = reply, 0
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.calls += 1
        films = [json.loads(line) for line in kw["messages"][0]["content"].split("<films>\n")[1].split("\n</films>")[0].splitlines()]
        out = [{"id": f["id"], "emoji": self.reply.get(f["title"], "🎬")} for f in films]
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps({"films": out}))])


MOM = {"title": "Memories of Murder", "tmdb_id": 11423, "keywords": ["serial killer", "rural"], "genres": ["Crime"]}
HEAT = {"title": "Heat", "tmdb_id": 949, "keywords": ["heist"], "genres": ["Crime"]}


class Fallback(unittest.TestCase):
    def test_keyword_then_genre(self):
        self.assertEqual(fallback(MOM), "🔪")
        self.assertEqual(fallback({"genres": ["Romance"]}), "💘")
        self.assertEqual(fallback({}), "🎞️")


class ChosenByClaude(unittest.TestCase):
    def test_cached_and_validated(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "emoji.json"
            client = FakeClient({"Memories of Murder": "🌾", "Heat": "🎬"})  # 🎬 is too generic: fall back
            got = Emojis(path, client=client, log=lambda m: None)({"mom": MOM, "heat": HEAT})
            self.assertEqual(got, {"mom": "🌾", "heat": "💰"})
            again = Emojis(path, client=client, log=lambda m: None)({"mom": MOM})
            self.assertEqual((again, client.calls), ({"mom": "🌾"}, 1))  # from the cache, no second call

    def test_no_key_means_fallback(self):
        e = Emojis(None, log=lambda m: None)
        e._client = lambda: None
        self.assertEqual(e({"mom": MOM}), {"mom": "🔪"})


if __name__ == "__main__":
    unittest.main()
