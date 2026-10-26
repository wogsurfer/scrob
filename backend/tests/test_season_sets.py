import unittest

from core.physical import season_numbers


class SeasonSetTests(unittest.TestCase):
    def test_reads_the_season_from_the_title(self):
        cases = {
            "Batman: The Animated Series: Season 1": {1},
            "Battlestar Galactica: Season Four": {4},
            "Breaking Bad: The Third Season": {3},
            "Justified: The Complete Fifth Season": {5},
            "Sherlock: Series Two": {2},
            "red vs. blue: SEASON 10": {10},
            "red vs. blue: SEASON FIVE": {5},
            "Sherlock: Complete Series One & Two": {1, 2},
            "Doctor Who: Series 1-3": {1, 2, 3},
        }
        for title, seasons in cases.items():
            self.assertEqual(season_numbers(title, 12), seasons, title)

    def test_final_season_is_the_last(self):
        self.assertEqual(season_numbers("Breaking Bad: The Final Season", 5), {5})
        self.assertEqual(season_numbers("Mad Men: The Final Season Part 2", 7), {7})
        self.assertEqual(season_numbers("Justified: The Complete Final Season", 6), {6})

    def test_no_season_in_the_title_means_all_of_it(self):
        self.assertEqual(season_numbers("Firefly", 1), {1})
        self.assertEqual(season_numbers("Battlestar Galactica: The Complete Series", 4), {1, 2, 3, 4})

    def test_seasons_beyond_the_show_are_ignored(self):
        self.assertEqual(season_numbers("Show: Season 9", 5), set())


if __name__ == "__main__":
    unittest.main()
