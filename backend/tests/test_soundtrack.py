import unittest

from core.soundtrack import _norm, album_matches, is_song, parse_track_listings, split_dialogue


def names(*people):
    return {_norm(p) for p in people}


class AlbumMatchTests(unittest.TestCase):
    def test_film_album_titles(self):
        self.assertTrue(album_matches("Reservoir Dogs: Music From the Original Motion Picture Soundtrack", "Reservoir Dogs", "movie"))
        self.assertTrue(album_matches("Top Gun", "Top Gun", "movie"))
        self.assertTrue(album_matches("Guardians of the Galaxy: Awesome Mix, Vol. 1", "Guardians of the Galaxy", "movie"))
        self.assertTrue(album_matches("Quentin Tarantino’s Inglourious Basterds: Motion Picture Soundtrack", "Inglourious Basterds", "movie"))
        self.assertFalse(album_matches("Quentin Tarantino’s Other Film", "Inglourious Basterds", "movie"))

    def test_other_albums_dont_match(self):
        self.assertFalse(album_matches("Guardians of the Galaxy: Original Score", "Guardians of the Galaxy", "movie"))
        self.assertFalse(album_matches("Reservoir Dogs: Bloody Days (Original Game Soundtrack)", "Reservoir Dogs", "movie"))
        self.assertFalse(album_matches("Bones and All", "Bones", "movie"))
        self.assertFalse(album_matches("Top Gun (Music Inspired by the Film)", "Top Gun", "movie"))

    def test_show_album_must_say_its_from_the_series(self):
        self.assertTrue(album_matches("Stranger Things: Music From the Netflix Original Series", "Stranger Things", "tv"))
        self.assertFalse(album_matches("Bones", "Bones", "tv"))


class IsSongTests(unittest.TestCase):
    composers = names("Kyle Dixon", "Michael Stein")
    cast = names("Steven Wright", "Harvey Keitel", "Tim Roth")
    writing = names("Quentin Tarantino")

    def check(self, **track):
        return is_song({"performers": [], "writers": [], "length": 200, **track}, self.composers, self.cast, self.writing)

    def test_song(self):
        self.assertTrue(self.check(performers=["Stealers Wheel"], writers=["Gerry Rafferty", "Joe Egan"]))

    def test_uncredited_track_is_score(self):
        # VisionQuest's score album on Wikipedia: titles and lengths, nobody credited.
        self.assertFalse(self.check(title="Me, Myself and AI", length=138))
        self.assertTrue(self.check(writers=["Harry Nilsson"]))

    def test_another_films_score(self):
        film = names("Ennio Morricone", "Bernard Herrmann")
        check = lambda **t: is_song({"performers": [], "writers": [], "length": 200, **t}, self.composers, self.cast, self.writing, film)
        # No words (or none known) and played by a film composer: score.
        self.assertFalse(check(performers=["Ennio Morricone"], words=False))
        self.assertFalse(check(performers=["Bernard Herrmann"]))
        self.assertFalse(check(performers=["The Film Studio Orchestra"], writers=["Ennio Morricone"]))
        # A song a film composer wrote, sung by someone else, stays.
        self.assertTrue(check(performers=["Joan Baez"], writers=["Ennio Morricone"], words=True))
        # A popular instrumental stays.
        self.assertTrue(check(performers=["Tomoyasu Hotei"], words=False))
        # A work MusicBrainz files as a soundtrack piece is score.
        self.assertFalse(check(performers=["The RZA"], score_work=True))

    def test_score_by_the_composer_even_as_a_duo(self):
        self.assertFalse(self.check(performers=["Kyle Dixon & Michael Stein"]))

    def test_dialogue(self):
        self.assertFalse(self.check(performers=["Steven Wright"], writers=["Quentin Tarantino"], length=15))
        self.assertFalse(self.check(performers=["Harvey Keitel and Tim Roth"], writers=["Quentin Tarantino"], length=62))
        # Long, but still the cast reading the script.
        self.assertFalse(self.check(performers=["Harvey Keitel"], writers=["Quentin Tarantino"], length=105))

    def test_cast_singing_someone_elses_song_is_kept(self):
        self.assertTrue(self.check(performers=["Tim Roth"], writers=["Harry Nilsson"], length=200))


class SplitDialogueTests(unittest.TestCase):
    def test_dialogue_part_dropped(self):
        track = {
            "title": "Pumpkin and Honey Bunny / Misirlou",
            "artist": "Tim Roth and Amanda Plummer / Dick Dale and His Del-Tones",
            "performers": ["Tim Roth", "Amanda Plummer", "Dick Dale and His Del-Tones"],
            "writers": ["Quentin Tarantino", "Nicholas Roubanis"],
            "length": 149,
        }
        got = split_dialogue(track, names("Tim Roth", "Amanda Plummer"), names("Quentin Tarantino"))
        self.assertEqual(got["title"], "Misirlou")
        self.assertEqual(got["artist"], "Dick Dale and His Del-Tones")
        self.assertEqual(got["writers"], ["Nicholas Roubanis"])

    def test_plain_track_unchanged(self):
        track = {"title": "Coconut", "artist": "Harry Nilsson", "performers": ["Harry Nilsson"], "writers": [], "length": 230}
        self.assertIs(split_dialogue(track, set(), set()), track)


class TrackListingTests(unittest.TestCase):
    def test_parses_songs_and_skips_score(self):
        wikitext = """
{{Track listing
| headline = Soundtrack
| writing_credits = yes
| extra_column = Performer
| title1 = [[Danger Zone (song)|Danger Zone]]
| writer1 = [[Giorgio Moroder]], Tom Whitlock
| extra1 = [[Kenny Loggins]]
| length1 = 3:36
| title2 = Mighty Wings
| extra2 = [[Cheap Trick]]
| length2 = 3:51
}}
{{Track listing
| headline = Original Score
| title1 = Top Gun Anthem
| length1 = 4:12
}}"""
        albums = parse_track_listings(wikitext)
        self.assertEqual(len(albums), 1)
        first = albums[0]["tracks"][0]
        self.assertEqual(first["title"], "Danger Zone")
        self.assertEqual(first["artist"], "Kenny Loggins")
        self.assertEqual(first["writers"], ["Giorgio Moroder", "Tom Whitlock"])
        self.assertEqual(first["length"], 216)
        self.assertEqual(len(albums[0]["tracks"]), 2)


if __name__ == "__main__":
    unittest.main()
