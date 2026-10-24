import asyncio
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

from core import awards, disk_cache, tvdb
from routers import shows


def _award(award_name, category, year, winner=False, details=None, person=None):
    return {
        "award_id": 1, "award_name": award_name, "category_id": 1, "category_name": category,
        "year": str(year), "is_winner": winner, "details": details, "person_name": person,
    }


def _wd(award_label, year, person_id, person_name, winner=False):
    family = award_label.split(" for ")[0]
    family = {"Academy Award": "Academy Awards", "Golden Globe Award": "Golden Globe Awards",
              "Primetime Emmy Award": "Primetime Emmy Awards"}.get(family, family)
    return {
        "award_name": family, "award_label": award_label, "category_name": award_label.split(" for ", 1)[1],
        "year": str(year), "is_winner": winner, "person_tmdb_id": person_id, "person_name": person_name,
    }


class TopicTests(unittest.TestCase):
    def test_award_bodies_wording_lines_up(self):
        self.assertEqual(awards.topic("Actress in a Supporting Role"), "actress-supporting")
        self.assertEqual(awards.topic("Best Supporting Actress"), "actress-supporting")
        self.assertEqual(awards.topic("Best Actor - Motion Picture Drama"), "actor-lead")
        self.assertEqual(awards.topic("Best Adapted Screenplay"), "screenplay-adapted")
        self.assertEqual(awards.topic("Best Art Direction"), "design")
        self.assertEqual(awards.topic("Best Director"), "director")
        self.assertEqual(awards.topic("Outstanding Casting for a Drama Series"), "casting")

    def test_sound_editing_is_not_film_editing(self):
        # Forrest Gump's Film Editing Oscar went to its sound editors.
        self.assertEqual(awards.topic("Best Sound Effects Editing"), "sound-editing")
        self.assertEqual(awards.topic("Film Editing"), "editing")
        self.assertEqual(awards.topic("Sound"), "sound")

    def test_guest_roles_are_their_own_topic(self):
        self.assertEqual(awards.topic("Outstanding Guest Actor in a Comedy Series"), "actor-guest")
        self.assertEqual(awards.topic("Outstanding Lead Actor in a Comedy Series"), "actor-lead")

    def test_join_and_split_names(self):
        self.assertEqual(awards.join_names(["A", "B", "C"]), "A, B & C")
        self.assertEqual(awards.split_names("A, B & C"), ["A", "B", "C"])

    def test_family(self):
        self.assertEqual(awards.family("Academy Awards"), "oscar")
        self.assertEqual(awards.family("Primetime Emmy Awards"), "emmy")
        self.assertEqual(awards.family("BAFTA Awards"), "bafta")
        self.assertIsNone(awards.family("MTV Movie Awards"))

    def test_credited_skips_whole_departments(self):
        crew = [{"id": i, "name": f"Mixer {i}", "job": "Sound Re-Recording Mixer"} for i in range(8)]
        self.assertEqual(awards.credited(crew, "Best Sound"), [])
        crew = [{"id": 1, "name": "Jennifer Lame", "job": "Editor"}]
        self.assertEqual(awards.credited(crew, "Best Film Editing"), [{"id": 1, "name": "Jennifer Lame"}])


class FilmNamingTests(unittest.TestCase):
    credits = {
        "cast": [
            {"id": 10, "name": "Cillian Murphy", "gender": 2, "order": 0},
            {"id": 11, "name": "Emily Blunt", "gender": 1, "order": 1},
            {"id": 12, "name": "Matt Damon", "gender": 2, "order": 2},
            {"id": 13, "name": "Robert Downey Jr.", "gender": 2, "order": 3},
            {"id": 14, "name": "Florence Pugh", "gender": 1, "order": 4},
        ],
        "crew": [
            {"id": 20, "name": "Christopher Nolan", "job": "Director"},
            {"id": 21, "name": "Jennifer Lame", "job": "Editor"},
        ],
    }

    def test_supporting_roles_follow_wikidata_not_billing(self):
        # Billing alone would give Supporting Actor to Damon and Supporting
        # Actress to Pugh; the record names Downey and Blunt.
        rows = [
            _award("Academy Awards", "Best Supporting Actor", 2024, True),
            _award("Academy Awards", "Best Supporting Actress", 2024),
            _award("Golden Globe Awards", "Best Supporting Actor - Motion Picture", 2024, True),
        ]
        wd = [
            _wd("Academy Award for Best Supporting Actor", 2024, 13, "Robert Downey Jr.", True),
            _wd("Academy Award for Best Supporting Actress", 2024, 11, "Emily Blunt"),
        ]
        named = awards._name_film_awards(rows, self.credits, wd)
        by_cat = {(r["award_name"], r["category_name"]): r for r in named}
        oscar_actor = by_cat[("Academy Awards", "Best Supporting Actor")]
        self.assertEqual(oscar_actor["person_name"], "Robert Downey Jr.")
        self.assertFalse(oscar_actor["name_inferred"])
        self.assertEqual(by_cat[("Academy Awards", "Best Supporting Actress")]["person_name"], "Emily Blunt")
        # The Globe nominee is the same person another body named in that category.
        self.assertEqual(by_cat[("Golden Globe Awards", "Best Supporting Actor - Motion Picture")]["person_name"], "Robert Downey Jr.")

    def test_guesses_are_marked_inferred(self):
        rows = [
            _award("BAFTA Awards", "Best Actor in a Leading Role", 2024, True),
            _award("BAFTA Awards", "Best Editing", 2024, True),
        ]
        named = awards._name_film_awards(rows, self.credits, [])
        self.assertEqual(named[0]["person_name"], "Cillian Murphy")
        self.assertTrue(named[0]["name_inferred"])
        self.assertEqual(named[1]["person_name"], "Jennifer Lame")
        self.assertTrue(named[1]["name_inferred"])

    def test_two_nominations_in_one_category_are_two_people(self):
        credits = {"cast": [
            {"id": 1, "name": "Marlon Brando", "gender": 2, "order": 0},
            {"id": 2, "name": "Al Pacino", "gender": 2, "order": 1},
        ], "crew": []}
        rows = [
            _award("BAFTA Awards", "Best Actor", 1973),
            _award("BAFTA Awards", "Best Actor", 1973),
        ]
        named = awards._name_film_awards(rows, credits, [])
        self.assertEqual({r["person_name"] for r in named}, {"Marlon Brando", "Al Pacino"})

    def test_shared_nomination_listed_per_nominee_is_one_row(self):
        # TVDB lists Memento's screenplay nomination once per writer.
        credits = {"cast": [], "crew": [{"id": 1, "name": "Christopher Nolan", "job": "Screenplay"}]}
        rows = [_award("Academy Awards", "Writing (Original Screenplay)", 2002)] * 2
        wd = [
            _wd("Academy Award for Best Writing, Original Screenplay", 2002, 1, "Christopher Nolan"),
            _wd("Academy Award for Best Writing, Original Screenplay", 2002, 2, "Jonathan Nolan"),
        ]
        named = awards._name_film_awards(rows, credits, wd)
        self.assertEqual([r["person_name"] for r in named], ["Christopher Nolan & Jonathan Nolan"])

    def test_other_bodies_placement_doesnt_rule_someone_out(self):
        # Uma Thurman: supporting at the Oscars, leading at BAFTA.
        credits = {"cast": [
            {"id": 1, "name": "John Travolta", "gender": 2, "order": 0},
            {"id": 2, "name": "Uma Thurman", "gender": 1, "order": 2},
            {"id": 3, "name": "Amanda Plummer", "gender": 1, "order": 5},
        ], "crew": []}
        rows = [
            _award("Academy Awards", "Actress in a Supporting Role", 1995),
            _award("BAFTA Awards", "Best Leading Actress", 1995),
        ]
        wd = [_wd("Academy Award for Best Supporting Actress", 1995, 2, "Uma Thurman")]
        named = awards._name_film_awards(rows, credits, wd)
        self.assertEqual(named[1]["person_name"], "Uma Thurman")

    def test_wikidata_record_dated_a_year_apart_is_one_nomination(self):
        credits = {"cast": [{"id": 9, "name": "Samuel L. Jackson", "gender": 2, "order": 1}], "crew": []}
        wd = [
            _wd("BAFTA Award for Best Actor in a Supporting Role", 1994, 9, "Samuel L. Jackson", True),
            _wd("BAFTA Award for Best Actor in a Supporting Role", 1995, 9, "Samuel L. Jackson", True),
        ]
        for w in wd:
            w["award_name"] = "BAFTA Awards"
        named = awards._name_film_awards([], credits, wd)
        self.assertEqual(len(named), 1)


class TvNamingTests(unittest.TestCase):
    def test_wikidata_names_and_adds_missing_nominations(self):
        rows = [_award("Golden Globe Awards", "Best Actress - Television Series Drama", 2000)]
        wd = [
            _wd("Golden Globe Award for Best Actress – Television Series Drama", 2000, 5, "Mariska Hargitay"),
            _wd("Primetime Emmy Award for Outstanding Lead Actress in a Drama Series", 2006, 5, "Mariska Hargitay", True),
        ]
        named = awards.name_tv_awards(rows, wd)
        self.assertEqual(len(named), 2)
        self.assertTrue(all(r["person_name"] == "Mariska Hargitay" for r in named))
        self.assertFalse(any(r.get("name_inferred") for r in named))

    def test_character_rows_never_borrow_a_fellow_nominee(self):
        # The guest-actor row names a character no one matched; it must not
        # fall back to the lead who was named that year (the Cranston case).
        rows = [
            _award("Primetime Emmy Awards", "Outstanding Supporting Actor in a Comedy Series", 2001,
                   person="Bryan Cranston"),
            _award("Primetime Emmy Awards", "Outstanding Guest Actor in a Comedy Series", 2001,
                   details='For playing "Grandpa Victor"'),
        ]
        named = awards.name_tv_awards(rows, [])
        guest = next(r for r in named if "Guest" in r["category_name"])
        self.assertIsNone(guest["person_name"])

    def test_same_role_fallback_is_marked_inferred(self):
        rows = [
            _award("Primetime Emmy Awards", "Outstanding Lead Actor in a Drama Series", 2008, person="Bryan Cranston"),
            _award("Golden Globe Awards", "Best Actor - Television Series Drama", 2008),
        ]
        named = awards.name_tv_awards(rows, [])
        globe = next(r for r in named if r["award_name"] == "Golden Globe Awards")
        self.assertEqual(globe["person_name"], "Bryan Cranston")
        self.assertTrue(globe["name_inferred"])


class CharacterMatchTests(unittest.TestCase):
    # (character, actor, episodes) as _show_roles returns them
    roles = [
        ("olivia benson", "Mariska Hargitay", 500),
        ("elliot stabler", "Christopher Meloni", 270),
        ("bernadette stabler", "Ellen Burstyn", 4),
        ("bernadette", "Someone Else", 1),
        ("hal", "Bryan Cranston", 151),
    ]

    def _name(self, details, category="Outstanding Guest Actress in a Drama Series"):
        with patch.object(shows, "_show_roles", AsyncMock(return_value=self.roles)):
            return asyncio.run(shows._name_actors([_award("Primetime Emmy Awards", category, 2009, details=details)], 2734, None))[0]

    def test_title_prefix_and_full_name(self):
        self.assertEqual(self._name('For playing "Det. Olivia Benson"')["person_name"], "Mariska Hargitay")

    def test_lone_first_name_is_not_a_full_name_match(self):
        self.assertEqual(self._name('For playing "Bernadette Stabler"')["person_name"], "Ellen Burstyn")

    def test_nickname(self):
        self.assertEqual(self._name('For playing "Bernie Stabler"')["person_name"], "Ellen Burstyn")

    def test_regular_credited_by_first_name(self):
        self.assertEqual(self._name('For playing "Hal Wilkerson"', "Outstanding Lead Actor in a Comedy Series")["person_name"], "Bryan Cranston")

    def test_unknown_character_stays_unnamed(self):
        self.assertIsNone(self._name('For playing "Grandpa Victor"')["person_name"])


class DiskCacheTests(unittest.TestCase):
    def test_round_trip_and_expiry(self):
        with tempfile.TemporaryDirectory() as d, patch.object(disk_cache.settings, "data_dir", Path(d)):
            self.assertIsNone(disk_cache.load("t", 1, 60))
            disk_cache.save("t", 1, [{"a": 1}])
            saved_at, value = disk_cache.load("t", 1, 60)
            self.assertEqual(value, [{"a": 1}])
            self.assertLessEqual(saved_at, time.time())
            self.assertIsNone(disk_cache.load("t", 1, -1))


class AwardIndexWaitTests(unittest.TestCase):
    def test_first_build_gives_up_waiting_but_keeps_building(self):
        async def slow_build(api_key):
            await asyncio.sleep(0.3)
            return [({"name": "Primetime Emmy Awards"}, {"name": "x"}, [])]

        async def run():
            with patch.object(tvdb, "_award_index", None), patch.object(tvdb, "_award_index_task", None), \
                 patch.object(tvdb, "_load_award_index", lambda: None), \
                 patch.object(tvdb, "_save_award_index", lambda: None), \
                 patch.object(tvdb, "_build_award_index", slow_build), \
                 patch.object(tvdb, "_AWARD_INDEX_WAIT", 0.05):
                with self.assertRaises(tvdb.AwardIndexBuilding):
                    await tvdb.get_award_index("key")
                await asyncio.sleep(0.4)
                self.assertEqual(len(await tvdb.get_award_index("key")), 1)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
