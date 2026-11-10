import unittest

from movie_night.linq_format import Pick, parse_reactions, pick_messages, pick_text
from movie_night.rules import Reaction

# Shape copied from the live M0 poll on Nov 10, 2026 (phone numbers replaced).
LIVE_MESSAGE = {
    "parts": [{
        "type": "text",
        "value": "Movie night test",
        "reactions": [
            {"type": "custom", "custom_emoji": "🥇", "is_me": False,
             "handle": {"handle": "+15550000001"}},
            {"type": "dislike", "custom_emoji": None, "is_me": False,
             "handle": {"handle": "+15550000002"}},
        ],
    }]
}


class PickFormat(unittest.TestCase):
    def test_text_then_standalone_link(self):
        p = Pick("Arrival", 2016, 116, ("Sci-Fi", "Drama", "Mystery"), "Paramount+",
                 "Quiet and smart, under two hours.", "https://www.youtube.com/watch?v=x")
        msgs = pick_messages(p)
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[1]["message"]["parts"], [{"type": "link", "value": "https://www.youtube.com/watch?v=x"}])
        text = msgs[0]["message"]["parts"][0]["value"]
        self.assertEqual(text, "🎬 Arrival (2016)\n1h 56m · Sci-Fi, Drama · Paramount+\nQuiet and smart, under two hours.")
        self.assertNotIn("http", text)

    def test_minimal_pick(self):
        self.assertEqual(pick_text(Pick("Heat")), "🎬 Heat")
        self.assertEqual(len(pick_messages(Pick("Heat"))), 1)


class Reactions(unittest.TestCase):
    def test_live_shape(self):
        r = parse_reactions(LIVE_MESSAGE)
        self.assertEqual(r.votes, [("+15550000001", Reaction.GOLD), ("+15550000002", Reaction.VETO)])
        self.assertEqual(r.ignored, [])

    def test_other_reactions_ignored(self):
        msg = {"parts": [{"reactions": [
            {"type": "love", "handle": {"handle": "a"}},
            {"type": "custom", "custom_emoji": "😂", "handle": {"handle": "b"}},
            {"type": "custom", "custom_emoji": "🚫", "handle": {"handle": "c"}},
            {"type": "custom", "custom_emoji": "🥇", "is_me": True, "handle": {"handle": "me"}},
        ]}]}
        r = parse_reactions(msg)
        self.assertEqual(r.votes, [("c", Reaction.VETO)])
        self.assertEqual(r.ignored, [("a", "love"), ("b", "😂")])


if __name__ == "__main__":
    unittest.main()
