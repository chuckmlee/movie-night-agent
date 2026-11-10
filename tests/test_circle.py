import json
import unittest
from types import SimpleNamespace

from movie_night.circle import extract, parse_feed, scores, verified_quote, voice

FEED = """<?xml version="1.0"?><rss xmlns:letterboxd="https://letterboxd.com" xmlns:tmdb="https://themoviedb.org"
xmlns:dc="http://purl.org/dc/elements/1.1/"><channel>
<item><title>Carrie, 1976 - ★★★★★</title><link>https://letterboxd.com/ann/film/carrie/</link>
<guid isPermaLink="false">letterboxd-review-1</guid><letterboxd:watchedDate>2026-10-01</letterboxd:watchedDate>
<letterboxd:filmTitle>Carrie</letterboxd:filmTitle><letterboxd:filmYear>1976</letterboxd:filmYear>
<letterboxd:memberRating>5.0</letterboxd:memberRating><letterboxd:memberLike>Yes</letterboxd:memberLike>
<tmdb:movieId>7340</tmdb:movieId><description><![CDATA[ <p><img src="x.jpg"/></p>
<p>De Palma's split screens are pure adrenaline.</p><p>The prom scene still makes me gasp.</p> ]]></description></item>
<item><title>A list</title><guid>letterboxd-list-9</guid><description>no film</description></item>
</channel></rss>"""


class FakeClient:
    """Stands in for anthropic.Anthropic: returns one canned extraction per review."""

    def __init__(self, quote):
        self.calls, self.quote = [], quote
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        ids = [line.split('"')[1] for line in kw["messages"][0]["content"].splitlines() if line.startswith("<review id=")]
        body = {"reviews": [{"id": i, "sentiment": 0.9, "loved": ["the prom scene"], "disliked": [],
                             "quote": self.quote} for i in ids]}
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(body))])


class Circle(unittest.TestCase):
    def test_parse_feed(self):
        [item] = parse_feed(FEED, "ann")
        self.assertEqual((item["tmdb_id"], item["stars"], item["liked"], item["year"]), (7340, 5.0, True, 1976))
        self.assertIn("split screens", item["text"])
        self.assertNotIn("img", item["text"])

    def test_quotes_must_be_verbatim(self):
        text = "De Palma's split screens are pure adrenaline.\nThe prom scene still makes me gasp."
        self.assertEqual(verified_quote("“The prom scene still makes me gasp.”", text), "The prom scene still makes me gasp.")
        self.assertIsNone(verified_quote("The prom scene is the best ever filmed.", text))  # paraphrase
        self.assertIsNone(verified_quote("", text))

    def test_extract_then_score(self):
        [item] = parse_feed(FEED, "ann")
        store = {"reviews": {item["id"]: item,
                             "r2": {**item, "id": "r2", "who": "bob", "stars": 2.0, "liked": False, "text": "Meh."}}}
        n = extract(store, client=FakeClient("The prom scene still makes me gasp."))
        self.assertEqual(n, 1)  # bob's one-word entry is too short to read
        call = FakeClient("x")
        extract({"reviews": {"a": {**item, "extract": None}}}, client=call)
        self.assertEqual(call.calls[0]["model"], "claude-opus-5-5")
        self.assertEqual(call.calls[0]["output_config"]["format"]["type"], "json_schema")
        f = scores(store)[7340]
        self.assertAlmostEqual(f["score"], 0.9 + 0.25 - 0.5)  # ann's words plus her heart; bob's 2 stars
        self.assertEqual(voice(f), "ann (5★): “The prom scene still makes me gasp.”")

    def test_made_up_quote_is_dropped(self):
        [item] = parse_feed(FEED, "ann")
        store = {"reviews": {item["id"]: item}}
        extract(store, client=FakeClient("Best horror film ever made."))
        self.assertIsNone(store["reviews"][item["id"]]["extract"]["quote"])
        self.assertEqual(voice(scores(store)[7340]), "ann (5★) loved it")


if __name__ == "__main__":
    unittest.main()
