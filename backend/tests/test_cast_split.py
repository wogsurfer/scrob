import asyncio
import unittest
from unittest import mock

from core import cast_split


def person(pid, name, character=""):
    return {"id": pid, "name": name, "character": character}


SEASONS = {
    # Zack is a regular in season 1 and guests in season 2; Sweets guests in
    # season 1 and joins the cast in season 2; Max only ever guests.
    1: {"credits": {"cast": [person(1, "Brennan"), person(2, "Zack")]},
        "episodes": [{"episode_number": 1, "air_date": "2005-09-13", "guest_stars": [person(3, "Sweets", "Lance Sweets"), person(4, "Max")]}]},
    2: {"credits": {"cast": [person(1, "Brennan"), person(3, "Sweets")]},
        "episodes": [{"episode_number": 1, "air_date": "2005-09-13", "guest_stars": [person(2, "Zack", "Zack Addy"), person(4, "Max")]}]},
}
SHOW = {
    "seasons": [{"season_number": 0}, {"season_number": 1}, {"season_number": 2}],
    "aggregate_credits": {"cast": [
        {"id": 1, "name": "Brennan", "total_episode_count": 2, "roles": [{"character": "Temperance Brennan"}]},
        {"id": 2, "name": "Zack", "total_episode_count": 2, "roles": [{"character": "Zack Addy"}]},
        {"id": 3, "name": "Sweets", "total_episode_count": 2, "roles": [{"character": "Lance Sweets"}]},
    ]},
}


class CastSplitTest(unittest.TestCase):
    def test_regulars_in_any_season_are_cast(self):
        async def season(tmdb_id, number, **_):
            return SEASONS[number]

        with mock.patch.object(cast_split.tmdb, "get_season", side_effect=season):
            split = asyncio.run(cast_split.build(1, SHOW, "key"))

        cast = {p["name"]: p for p in split["cast"]}
        self.assertEqual(set(cast), {"Brennan", "Zack", "Sweets"})
        self.assertEqual(cast["Zack"]["seasons"], [1])
        self.assertEqual(cast["Sweets"]["seasons"], [2])
        self.assertEqual(cast["Zack"]["guest_episodes"], 1)
        # His regular episodes leave out the guest spot TMDB's total counts.
        self.assertEqual(cast["Zack"]["episode_count"], 1)
        self.assertEqual(cast["Brennan"]["episode_count"], 2)
        # Their guest spots are kept as guest spots too.
        guests = {p["name"]: p for p in split["guest_stars"]}
        self.assertEqual(set(guests), {"Max", "Zack", "Sweets"})
        self.assertEqual(guests["Max"]["episode_count"], 2)
        self.assertEqual((guests["Zack"]["episode_count"], guests["Zack"]["character"], guests["Zack"]["also_regular"]), (1, "Zack Addy", True))
        self.assertFalse(guests["Max"]["also_regular"])

    def test_freshness(self):
        self.assertFalse(cast_split.is_fresh({}, "Ended"))
        self.assertTrue(cast_split.is_fresh({"cast_split": {"at": cast_split.datetime.now(cast_split.UTC).isoformat()}}, "Ended"))
