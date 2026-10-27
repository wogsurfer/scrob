import unittest
from datetime import date

from core.episode_refresh import needs_refresh

TODAY = date(2026, 10, 27)


class NeedsRefreshTests(unittest.TestCase):
    def test_placeholder_saved_before_airing(self):
        # The Diplomat 4x01: saved on release day as "Episode 1".
        self.assertTrue(needs_refresh("Episode 1", "2026-10-15", date(2026, 10, 15), TODAY))
        # House of the Dragon 3x08: saved a week before it aired, months ago.
        self.assertTrue(needs_refresh("Episode 8", "2026-08-09", date(2026, 8, 3), TODAY))

    def test_title_that_really_is_episode_n_settles(self):
        # Adolescence: checked long after airing, so it's the real title.
        self.assertFalse(needs_refresh("Episode 1", "2025-03-13", date(2026, 8, 3), TODAY))

    def test_recent_and_upcoming_until_settled(self):
        self.assertTrue(needs_refresh("Firewall", "2026-10-27", date(2026, 10, 1), TODAY))
        self.assertTrue(needs_refresh("Immolation", "2026-11-03", date(2026, 10, 27), TODAY))
        self.assertFalse(needs_refresh("Firewall", "2026-10-20", date(2026, 10, 24), TODAY))

    def test_outside_the_window_or_undated(self):
        self.assertFalse(needs_refresh("Pilot", "2026-12-25", date(2026, 10, 1), TODAY))
        self.assertFalse(needs_refresh("Pilot", "2026-09-01", date(2026, 8, 1), TODAY))
        self.assertFalse(needs_refresh("Episode 1", None, date(2026, 8, 1), TODAY))


if __name__ == "__main__":
    unittest.main()
