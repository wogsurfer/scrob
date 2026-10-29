import unittest
from datetime import date

from core.holidays import easter_sunday, nth_weekday, theme_for


def key(day):
    theme = theme_for(day)
    return theme["key"] if theme else None


class HolidaysTest(unittest.TestCase):
    def test_easter(self):
        self.assertEqual(easter_sunday(2026), date(2026, 4, 5))
        self.assertEqual(easter_sunday(2027), date(2027, 3, 28))
        self.assertEqual(key(date(2027, 3, 26)), "easter")   # Good Friday
        self.assertEqual(key(date(2027, 3, 29)), "easter")   # Easter Monday
        self.assertIsNone(key(date(2027, 3, 30)))

    def test_moving_days(self):
        self.assertEqual(nth_weekday(2027, 5, 6, 2), date(2027, 5, 9))     # Mother's Day
        self.assertEqual(nth_weekday(2027, 6, 6, 3), date(2027, 6, 20))    # Father's Day
        self.assertEqual(nth_weekday(2026, 11, 3, 4), date(2026, 11, 26))  # Thanksgiving

    def test_spans_and_overlaps(self):
        self.assertEqual(key(date(2026, 12, 18)), "christmas")
        self.assertEqual(key(date(2026, 12, 31)), "new_year")    # New Year wins inside Christmas
        self.assertEqual(key(date(2027, 1, 1)), "new_year")
        self.assertEqual(key(date(2027, 1, 6)), "christmas")
        self.assertEqual(key(date(2026, 10, 21)), "back_to_the_future")
        self.assertEqual(key(date(2026, 10, 29)), "halloween")
        self.assertEqual(key(date(2027, 5, 4)), "star_wars")
        self.assertEqual(key(date(2027, 2, 13)), "valentines")
        self.assertEqual(key(date(2027, 3, 17)), "st_patricks")
        self.assertEqual(key(date(2027, 3, 15)), "oscars")
        self.assertIsNone(key(date(2026, 7, 10)))
