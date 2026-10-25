import unittest

from core.physical import franchise_name, franchise_order


class FranchiseSortTests(unittest.TestCase):
    def test_release_order(self):
        parts = [
            {"id": 3, "title": "Fast Five", "release_date": "2011-04-20"},
            {"id": 1, "title": "The Fast and the Furious", "release_date": "2001-06-22"},
            {"id": 2, "title": "2 Fast 2 Furious", "release_date": "2003-06-05"},
        ]
        self.assertEqual(franchise_order(parts), [1, 2, 3])

    def test_episode_order_beats_release_date(self):
        parts = [
            {"id": 4, "title": "Star Wars: Episode IV - A New Hope", "release_date": "1977-05-25"},
            {"id": 1, "title": "Star Wars: Episode I - The Phantom Menace", "release_date": "1999-05-19"},
        ]
        self.assertEqual(franchise_order(parts), [1, 4])

    def test_unreleased_go_last(self):
        parts = [{"id": 9, "title": "Next One"}, {"id": 1, "title": "First", "release_date": "1990-01-01"}]
        self.assertEqual(franchise_order(parts), [1, 9])

    def test_name(self):
        self.assertEqual(franchise_name("The Fast and the Furious Collection"), "The Fast and the Furious")
        self.assertEqual(franchise_name("Alien"), "Alien")


if __name__ == "__main__":
    unittest.main()
