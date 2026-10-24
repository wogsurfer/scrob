import unittest

from core.episode_badges import episode_badge, season_badges


class EpisodeBadgeTests(unittest.TestCase):
    def test_premieres(self):
        self.assertEqual(episode_badge(1, 1, "standard"), "Series premiere")
        self.assertEqual(episode_badge(4, 1, "standard"), "Season premiere")
        self.assertEqual(episode_badge(2, 9, "standard", previous_type="mid_season"), "Mid-season premiere")

    def test_finales(self):
        self.assertEqual(episode_badge(2, 8, "mid_season"), "Mid-season finale")
        self.assertEqual(episode_badge(2, 7, "finale", show_status="Returning Series"), "Season finale")
        self.assertEqual(episode_badge(5, 16, "finale", show_status="Ended"), "Series finale")

    def test_plain_episodes_and_specials(self):
        self.assertIsNone(episode_badge(12, 6, "standard"))
        self.assertIsNone(episode_badge(0, 1, "standard"))

    def test_season_badges(self):
        season = {"season_number": 3, "episodes": [
            {"episode_number": n, "episode_type": t}
            for n, t in [(1, "standard"), (2, "standard"), (3, "mid_season"), (4, "standard"), (5, "finale")]
        ]}
        self.assertEqual(season_badges(season), {
            1: "Season premiere", 3: "Mid-season finale", 4: "Mid-season premiere", 5: "Season finale",
        })


if __name__ == "__main__":
    unittest.main()
