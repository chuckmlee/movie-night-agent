import unittest

from movie_night.tmdb import Availability, parse_availability, parse_details, pick_trailer
from movie_night.watchlist import parse_film_page

# Trimmed from live TMDB and Letterboxd responses for Arrival (Nov 10, 2026).
ARRIVAL = {
    "id": 329865,
    "runtime": 116,
    "genres": [{"id": 18, "name": "Drama"}, {"id": 878, "name": "Science Fiction"}, {"id": 9648, "name": "Mystery"}],
    "overview": "Taking place after alien crafts land around the world...",
    "videos": {"results": [
        {"site": "YouTube", "key": "dyFa0tOwA1k", "type": "Clip", "official": True, "iso_639_1": "en"},
        {"site": "YouTube", "key": "7W1m5ER3I1Y", "name": "Final Trailer", "type": "Trailer", "official": True,
         "iso_639_1": "en", "published_at": "2016-10-20T15:00:00.000Z"},
        {"site": "YouTube", "key": "tFMo3UJ4B4g", "name": "Trailer", "type": "Trailer", "official": True,
         "iso_639_1": "en", "published_at": "2016-08-16T14:00:03.000Z"},
    ]},
    "watch/providers": {"results": {"US": {
        "buy": [{"provider_id": 10}, {"provider_id": 2}, {"provider_id": 3}],
        "rent": [{"provider_id": 2}, {"provider_id": 10}],
    }}},
}
LB_PAGE = ('<body class="film backdropped" data-type="film" data-tmdb-type="movie" data-tmdb-id="329865">'
           '<script>{"aggregateRating":{"ratingValue":4.14,"ratingCount":2806757}}</script>')


class Details(unittest.TestCase):
    def test_arrival(self):
        e = parse_details(ARRIVAL)
        self.assertEqual(e.runtime_min, 116)
        self.assertEqual(e.genres, ["Drama", "Science Fiction", "Mystery"])
        self.assertEqual(e.trailer_url, "https://www.youtube.com/watch?v=tFMo3UJ4B4g")
        self.assertEqual(e.availability.included, [])
        self.assertEqual(e.availability.rent, ["Prime Video", "Apple TV"])  # store preference order
        self.assertEqual(e.availability.where(), "Rent on Prime Video")

    def test_trailer_prefers_official_english_over_teaser(self):
        vids = [
            {"site": "YouTube", "key": "teaser", "name": "Teaser", "type": "Trailer", "official": True,
             "iso_639_1": "en", "published_at": "2016-01-01"},
            {"site": "YouTube", "key": "fan", "name": "Trailer", "type": "Trailer", "official": False,
             "iso_639_1": "en", "published_at": "2015-01-01"},
            {"site": "YouTube", "key": "main", "name": "Official Trailer", "type": "Trailer", "official": True,
             "iso_639_1": "en", "published_at": "2016-06-01"},
        ]
        self.assertTrue(pick_trailer(vids).endswith("main"))
        self.assertIsNone(pick_trailer([{"site": "Vimeo", "type": "Trailer", "key": "x"}]))


class Availability_(unittest.TestCase):
    def test_household_services_and_ad_tiers(self):
        a = parse_availability({"flatrate": [{"provider_id": 1796}, {"provider_id": 1899}, {"provider_id": 337}]})
        self.assertEqual(a.included, ["Netflix", "Max"])  # Disney+ (337) is not a household service
        self.assertEqual(a.where(), "On Netflix and Max")

    def test_nothing(self):
        self.assertIsNone(parse_availability(None).where())
        self.assertEqual(Availability(buy=["Apple TV"]).where(), "Buy on Apple TV")


class FilmPage(unittest.TestCase):
    def test_letterboxd_page(self):
        p = parse_film_page(LB_PAGE)
        self.assertEqual((p.tmdb_id, p.tmdb_type, p.rating, p.rating_count), (329865, "movie", 4.14, 2806757))

    def test_unrated(self):
        p = parse_film_page('<body data-tmdb-type="tv" data-tmdb-id="12">')
        self.assertEqual((p.tmdb_id, p.tmdb_type, p.rating), (12, "tv", None))



class TitleMatch(unittest.TestCase):
    def test_articles_and_votes(self):
        from movie_night.tmdb import best_match
        results = [{"id": 1, "title": "The Piercing Gaze: Memories of a Bizarre Murder", "vote_count": 0},
                   {"id": 2, "title": "Memories of a Murderer: The Nilsen Tapes", "vote_count": 101},
                   {"id": 3, "title": "Memories of Murder", "vote_count": 4933}]
        self.assertEqual(best_match("Memories of a Murder", results)["id"], 3)
        self.assertEqual(best_match("wicker man", [{"id": 9, "title": "The Wicker Man", "vote_count": 5},
                                                   {"id": 8, "title": "The Wicker Man", "vote_count": 900}])["id"], 8)


if __name__ == "__main__":
    unittest.main()
