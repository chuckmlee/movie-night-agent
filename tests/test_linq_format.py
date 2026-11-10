import unittest

from movie_night.linq_format import Pick, parse_reactions, pick_from_cache, pick_message, pick_text, trailer_message, wants_trailer
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
    def test_poster_then_text_in_one_message(self):
        p = Pick("Arrival", 2016, 116, ("Sci-Fi", "Drama", "Mystery"), "Paramount+",
                 "Quiet and smart, under two hours.", "https://www.youtube.com/watch?v=x",
                 "https://image.tmdb.org/t/p/w500/a.jpg")
        parts = pick_message(p)["message"]["parts"]
        self.assertEqual(parts[0], {"type": "media", "url": "https://image.tmdb.org/t/p/w500/a.jpg"})
        text = parts[1]["value"]
        self.assertEqual(text, "🎬 Arrival (2016)\n1h 56m · Sci-Fi, Drama · Paramount+\n• Quiet and smart, under two hours.")
        self.assertNotIn("http", text)

    def test_minimal_pick(self):
        self.assertEqual(pick_text(Pick("Heat")), "🎬 Heat")
        self.assertEqual(pick_message(Pick("Heat"))["message"]["parts"],
                         [{"type": "text", "value": "🎬 Heat", "text_decorations": [{"range": [3, 7], "style": "bold"}]}])

    def test_emoji_bold_title_bullets_and_italic_label(self):
        p = Pick("Memories of Murder", 2003, 132, ("Crime", "Drama"), "Max",
                 "Like Zodiac (5★) and Se7en (4.5★) · ★ 4.4 on Letterboxd\n💬 ann (5★): “Pure dread.”",
                 emoji="🌾", label="🃏 Wildcard: not on your watchlist")
        part = pick_message(p)["message"]["parts"][0]
        self.assertEqual(part["value"], "🌾 Memories of Murder (2003)\n2h 12m · Crime, Drama · Max\n"
                         "• Like Zodiac (5★) and Se7en (4.5★)\n• ★ 4.4 on Letterboxd\n• 💬 ann (5★): “Pure dread.”\n"
                         "🃏 Wildcard: not on your watchlist")
        units = part["value"].encode("utf-16-le")

        def span(r):
            return units[2 * r[0]:2 * r[1]].decode("utf-16-le")

        bold, italic = part["text_decorations"]
        self.assertEqual((span(bold["range"]), bold["style"]), ("Memories of Murder", "bold"))
        self.assertEqual((span(italic["range"]), italic["style"]), ("🃏 Wildcard: not on your watchlist", "italic"))

    def test_trailer_is_a_threaded_standalone_link(self):
        self.assertEqual(trailer_message("https://www.youtube.com/watch?v=x", "msg-1"),
                         {"message": {"parts": [{"type": "link", "value": "https://www.youtube.com/watch?v=x"}],
                                      "reply_to": {"message_id": "msg-1"}}})


class FromCache(unittest.TestCase):
    def test_cache_entry(self):
        entry = {"title": "Arrival", "year": 2016, "runtime_min": 116, "genres": ["Drama", "Science Fiction"],
                 "trailer_url": "https://www.youtube.com/watch?v=tFMo3UJ4B4g",
                 "availability": {"included": [], "rent": ["Prime Video"], "buy": []}}
        self.assertIsNone(pick_from_cache(entry).poster_url)
        self.assertEqual(pick_from_cache({**entry, "poster_path": "/a.jpg"}).poster_url,
                         "https://image.tmdb.org/t/p/w500/a.jpg")
        self.assertEqual(pick_text(pick_from_cache(entry)),
                         "🎬 Arrival (2016)\n1h 56m · Drama, Science Fiction · Rent on Prime Video")


class Reactions(unittest.TestCase):
    def test_live_shape(self):
        r = parse_reactions(LIVE_MESSAGE)
        self.assertEqual(r.votes, [("+15550000001", Reaction.GOLD), ("+15550000002", Reaction.VETO)])
        self.assertEqual(r.ignored, [])

    def test_eyes_asks_for_trailer_and_is_not_a_vote(self):
        m = {"parts": [{"type": "media", "reactions": [
            {"type": "custom", "custom_emoji": "👀", "is_me": False, "handle": {"handle": "+1"}}]}]}
        self.assertTrue(wants_trailer(m))
        self.assertEqual((parse_reactions(m).votes, parse_reactions(m).ignored), ([], []))
        self.assertFalse(wants_trailer({"parts": [{"type": "text", "reactions": [
            {"type": "custom", "custom_emoji": "👀", "is_me": True}]}]}))

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
