import io
import unittest
from datetime import date

from core.clz_import import parse_clz, parse_date
from routers.physical import clean_product_title

EXPORT = """<?xml version="1.0" encoding="UTF-8"?>
<movieinfo>
<movielist>
  <movie>
    <id>134879</id>
    <index>0</index>
    <coverfront>C:\\Images\\GoodWillHunting.jpg</coverfront>
    <imdburl>https://www.imdb.com/title/tt0119217/?ref_=ref_ext_clz</imdburl>
    <imdbrating>8.3</imdbrating>
    <tmdbid>489</tmdbid>
    <tmdburl>http://themoviedb.org/movie/489</tmdburl>
    <format><displayname>Blu-ray</displayname></format>
    <collectionstatus listid="3">In Collection</collectionstatus>
    <store><displayname>Barnes &amp; Noble</displayname></store>
    <boxset />
    <purchasedate><date>08/21/2024</date></purchasedate>
    <title>Good Will Hunting</title>
    <myrating>9</myrating>
    <seenit boolvalue="1">Yes</seenit>
    <edition><displayname>15th Anniversary Edition</displayname></edition>
    <releasedate><year><displayname>1997</displayname></year><date>1997</date></releasedate>
    <dvdreleasedate><date>08/21/2012</date></dvdreleasedate>
    <upc>032429344069</upc>
    <extrafeatures>Commentary</extrafeatures>
    <layers listid="1">Single Side, Dual Layer</layers>
    <hdr listid="0">N/A</hdr>
    <runtime>126</runtime>
    <nritems>1</nritems>
    <istvseries boolvalue="0">No</istvseries>
    <regions><region><displayname>Region A</displayname></region><region><displayname>Region B</displayname></region></regions>
    <audios><audio><displayname>DTS-HD Master Audio 5.1 [English]</displayname></audio></audios>
    <crew>
      <crewmember><role id="dfDirector">Director</role><person><displayname>Gus Van Sant</displayname></person><sequence>1</sequence></crewmember>
    </crew>
    <discs><disc><title>Disc 01</title><extrafeatures>Commentary</extrafeatures><format><displayname>Blu-ray</displayname></format></disc></discs>
    <userdefinedvalues>
      <userdefinedvalue fieldid="dfUserField101000">
        <userdefinedfield><label>Movie Tagline</label></userdefinedfield>
        <value>Some people can never believe in themselves.</value>
      </userdefinedvalue>
      <userdefinedvalue fieldid="dfUserField101010">
        <userdefinedfield><label>Cinema</label></userdefinedfield>
        <value id="1">No</value>
        <lookupitem><displayname>No</displayname></lookupitem>
      </userdefinedvalue>
    </userdefinedvalues>
  </movie>
  <movie>
    <id>2138</id>
    <title>Planet of the Apes</title>
    <collectionstatus listid="1">On Wish List</collectionstatus>
    <boxset>
      <displayname>Planet of the Apes: 40-Year Evolution</displayname>
      <purchasedate><date>07/27/2008</date></purchasedate>
      <store><displayname>Amazon UK</displayname></store>
    </boxset>
  </movie>
</movielist>
</movieinfo>"""


class ClzImportTests(unittest.TestCase):
    def setUp(self):
        self.items, self.box_sets = parse_clz(io.StringIO(EXPORT))

    def test_release_columns(self):
        item = self.items[0]
        self.assertEqual(item["clz_id"], 134879)
        self.assertEqual(item["status"], "owned")
        self.assertEqual(item["tmdb_id"], 489)
        self.assertEqual(item["release_year"], 1997)
        self.assertEqual(item["edition"], "15th Anniversary Edition")
        self.assertEqual(item["store"], "Barnes & Noble")
        self.assertEqual(item["barcode"], "032429344069")
        self.assertEqual(item["purchase_date"], date(2024, 8, 21))
        self.assertEqual(item["disc_release_date"], date(2012, 8, 21))
        self.assertEqual(item["my_rating"], 9)
        self.assertTrue(item["seen_it"])
        self.assertFalse(item["is_tv"])
        self.assertIsNone(item["index_no"])
        self.assertIsNone(item["box_set"])

    def test_specs(self):
        specs = self.items[0]["specs"]
        self.assertEqual(specs["imdb_id"], "tt0119217")
        self.assertEqual(specs["regions"], ["Region A", "Region B"])
        self.assertEqual(specs["audio"], ["DTS-HD Master Audio 5.1 [English]"])
        self.assertEqual(specs["crew"][0]["role"], "Director")
        self.assertEqual(specs["tagline"], "Some people can never believe in themselves.")
        self.assertEqual(specs["seen_in_cinema"], "No")
        self.assertNotIn("hdr", specs)
        # A single disc's extras repeat the release's, so aren't kept twice.
        self.assertNotIn("extra_features", specs["discs"][0])

    def test_wishlist_and_box_set(self):
        item = self.items[1]
        self.assertEqual(item["status"], "wishlist")
        self.assertEqual(item["box_set"], "Planet of the Apes: 40-Year Evolution")
        self.assertEqual(self.box_sets, [{
            "name": "Planet of the Apes: 40-Year Evolution", "upc": None, "cover_front": None, "cover_back": None,
            "purchase_date": date(2008, 7, 27), "release_date": None, "store": "Amazon UK",
            "condition": None, "notes": None,
        }])

    def test_dates(self):
        self.assertEqual(parse_date("09/04/2024 19:08:49"), date(2024, 9, 4))
        self.assertIsNone(parse_date("1997"))
        self.assertIsNone(parse_date(None))

    def test_product_titles(self):
        self.assertEqual(clean_product_title("Dune (4K Ultra HD + Blu-ray) [Steelbook]"), "Dune")
        self.assertEqual(clean_product_title("Good Will Hunting 15th Anniversary Edition Blu-ray"), "Good Will Hunting 15th Anniversary Edition")
        self.assertEqual(clean_product_title("The Matrix [Blu-ray]"), "The Matrix")


if __name__ == "__main__":
    unittest.main()
