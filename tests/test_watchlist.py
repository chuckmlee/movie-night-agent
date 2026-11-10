import unittest

from movie_night.watchlist import parse_page

SAMPLE = """
<li class="griditem"><div class="react-component" data-component-class="LazyPoster"
 data-item-name="Fatherland (2026)" data-item-slug="fatherland-2026" data-item-link="/film/fatherland-2026/"
 data-postered-identifier='{&quot;lid&quot;:&quot;TbK4&quot;,&quot;uid&quot;:&quot;film:1315318&quot;}'></div></li>
<li class="griditem"><div class="react-component" data-component-class="LazyPoster"
 data-item-name="Untitled Thing" data-item-slug="untitled-thing"></div></li>
<a href="/someone/watchlist/page/2/">2</a><a href="/someone/watchlist/page/41/">41</a>
"""


class WatchlistParseTest(unittest.TestCase):
    def test_parse(self):
        films, last = parse_page(SAMPLE)
        self.assertEqual(last, 41)
        self.assertEqual(len(films), 2)
        self.assertEqual(films[0].title, "Fatherland")
        self.assertEqual(films[0].year, 2026)
        self.assertEqual(films[0].letterboxd_id, "film:1315318")
        self.assertIsNone(films[1].year)

    def test_empty(self):
        self.assertEqual(parse_page("<html></html>"), ([], 1))


if __name__ == "__main__":
    unittest.main()
