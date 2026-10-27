import unittest
from datetime import datetime

from routers.calendar import MALTA_TZ, tvmaze_release


def malta(*args):
    return datetime(*args, tzinfo=MALTA_TZ)


class StreamingReleaseTests(unittest.TestCase):
    def ep(self, airdate, airtime=""):
        return {"airdate": airdate, "airtime": airtime, "airstamp": f"{airdate}T12:00:00+00:00"}

    def test_disney_drops_the_next_morning_in_malta(self):
        # VisionQuest: listed for Tuesday, out 6pm Pacific = 2am Wednesday in Malta.
        self.assertEqual(tvmaze_release(self.ep("2026-10-27"), "Disney+"), malta(2026, 10, 28, 2, 0))
        # After the US clocks change too (Pacific is then UTC-8).
        self.assertEqual(tvmaze_release(self.ep("2026-11-10"), "Disney+"), malta(2026, 11, 11, 3, 0))

    def test_netflix_and_apple(self):
        self.assertEqual(tvmaze_release(self.ep("2026-11-13"), "Netflix"), malta(2026, 11, 13, 9, 0))
        self.assertEqual(tvmaze_release(self.ep("2026-11-13"), "Apple TV"), malta(2026, 11, 13, 3, 0))

    def test_known_time_or_other_channel_uses_the_airstamp(self):
        timed = {"airdate": "2026-10-27", "airtime": "21:00", "airstamp": "2026-10-28T01:00:00+00:00"}
        self.assertEqual(tvmaze_release(timed, "Disney+"), malta(2026, 10, 28, 2, 0))
        self.assertEqual(tvmaze_release(self.ep("2026-10-27"), "Peacock"), malta(2026, 10, 27, 13, 0))
        self.assertEqual(tvmaze_release(self.ep("2026-10-27")), malta(2026, 10, 27, 13, 0))


if __name__ == "__main__":
    unittest.main()
