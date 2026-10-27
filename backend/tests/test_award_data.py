import unittest

from core import award_data
from core.awards import _name_film_awards, name_tv_awards, record_row, tv_record_rows

OSCARS_TSV = (
    "Ceremony\tYear\tClass\tCanonicalCategory\tCategory\tFilm\tFilmId\tName\tNominees\tNomineeIds\tWinner\tDetail\tNote\tCitation\n"
    "97\t2024\tActing\tACTRESS IN A LEADING ROLE\tACTRESS IN A LEADING ROLE\tAnora\ttt28607951\tMikey Madison\tMikey Madison\tnm8933107\tTrue\tAni\t\t\n"
    "97\t2024\tTitle\tBEST PICTURE\tBEST PICTURE\tAnora\ttt28607951\tAlex Coco, Samantha Quan and Sean Baker, Producers\tAlex Coco|Samantha Quan|Sean Baker\tnm7866544|nm1013476|nm0048918\tTrue\t\t\t\n"
    "97\t2024\tSciTech\tSCIENTIFIC AND ENGINEERING AWARD\tSCIENTIFIC AND ENGINEERING AWARD\t\t\tSomeone\tSomeone\tnm1\tTrue\t\t\t\n"
)

EMMYS_CSV = (
    "year,category,canonical_category,nominee,nominee_id,work,work_id,role,network,winner\n"
    '2024,Outstanding Writing for a Comedy Series,x,"Lucia Aniello, Paul W. Downs, and Jen Statsky","",Hacks: "Bulletproof",,,HBO,true\n'
    "2025,Outstanding Supporting Actor in a Drama Series,x,Tramell Tillman,,Severance,,Seth Milchick,Apple TV+,true\n"
    "2025,Outstanding Supporting Actor in a Drama Series,x,Zach Cherry,,Severance,,Dylan George,Apple TV+,false\n"
)

FILMS_TTL = """@prefix msh: <http://example.org/ontologies/MovieSHACL3#> .

msh:Film_Kill_Bill_Volume_1_2003 a msh:Film ;
    rdfs:label "Kill Bill: Volume 1" ;
    msh:releaseYear "2003"^^xsd:gYear ;
    msh:title "Kill Bill: Volume 1" .

msh:Film_Anora_2024 a msh:Film ;
    rdfs:label "Anora" ;
    msh:hasIdentifier <https://www.imdb.com/title/tt28607951>,
        <https://www.themoviedb.org/movie/1064213> ;
    msh:title "Anora" .
"""

PEOPLE_TTL = """msh:Person_Uma_Thurman a msh:Person ;
    rdfs:label "Uma Thurman" ;
    msh:fullName "Uma Thurman" ;
    msh:hasIdentifier <https://www.imdb.com/name/nm0000235> .

msh:Person_Alex_Coco a msh:Person ;
    msh:fullName "Alex Coco" .

msh:Person_Sean_Baker a msh:Person ;
    msh:fullName "Sean Baker" ;
    msh:hasIdentifier <https://www.imdb.com/name/nm0048918> .
"""

BAFTAS_TTL = """msh:Category_bafta_Best_Film a msh:AwardCategory ;
    rdfs:label "Best Film" .

msh:Nomination_a a msh:Nomination ;
    msh:hasCategory msh:Category_bafta_Best_Actress_in_a_Leading_Role ;
    msh:hasFilm msh:Film_Kill_Bill_Volume_1_2003 ;
    msh:hasNominee msh:Person_Uma_Thurman ;
    msh:nomineeType "PERSON" ;
    msh:winner false ;
    msh:yearFilm "2003"^^xsd:gYear .

msh:Nomination_b a msh:Nomination ;
    msh:hasCategory msh:Category_bafta_Best_Film ;
    msh:hasFilm msh:Film_Anora_2024 ;
    msh:hasNominee msh:Person_Sean_Baker ;
    msh:nomineeType "COLLABORATION" ;
    msh:winner false ;
    msh:yearFilm "2024"^^xsd:gYear .

msh:Nomination_c a msh:Nomination ;
    msh:hasCategory msh:Category_bafta_Best_Film ;
    msh:hasFilm msh:Film_Anora_2024 ;
    msh:hasNominee msh:Person_Alex_Coco ;
    msh:nomineeType "COLLABORATION" ;
    msh:winner false ;
    msh:yearFilm "2024"^^xsd:gYear .
"""


def load(**texts):
    records = award_data.build({"oscars": OSCARS_TSV, "emmys": EMMYS_CSV, "globes": "", "baftas": BAFTAS_TTL,
                                "films": FILMS_TTL, "people": PEOPLE_TTL, **texts})
    award_data._use(records, 0)
    return records


class ParseTests(unittest.TestCase):
    def test_oscars(self):
        rows = award_data.parse_oscars(OSCARS_TSV)
        self.assertEqual(len(rows), 2)  # the Sci-Tech award isn't a film's
        actress, picture = rows
        self.assertEqual((actress["category"], actress["year"], actress["winner"]), ("Actress in a Leading Role", 2025, True))
        self.assertEqual(picture["people"][2], {"name": "Sean Baker", "imdb": "nm0048918"})
        self.assertEqual(picture["works"][0]["imdb"], "tt28607951")

    def test_emmys(self):
        writing, tillman, _ = award_data.parse_emmys(EMMYS_CSV)
        self.assertEqual([p["name"] for p in writing["people"]], ["Lucia Aniello", "Paul W. Downs", "Jen Statsky"])
        self.assertEqual(writing["works"][0]["title"], "Hacks")
        self.assertEqual(writing["detail"], 'For episode "Bulletproof"')
        self.assertEqual(tillman["detail"], 'For playing "Seth Milchick"')

    def test_fckg(self):
        films = award_data.parse_turtle(FILMS_TTL)
        people = award_data.parse_turtle(PEOPLE_TTL)
        uma, film = award_data.parse_fckg(award_data.BAFTAS, BAFTAS_TTL, films, people)
        self.assertEqual((uma["year"], uma["people"][0]["imdb"]), (2004, "nm0000235"))
        self.assertEqual(uma["category"], "Best Actress in a Leading Role")
        # One shared Best Film nomination, not one per producer.
        self.assertEqual([p["name"] for p in film["people"]], ["Sean Baker", "Alex Coco"])
        self.assertEqual(film["works"][0]["tmdb"], 1064213)


class LookupTests(unittest.TestCase):
    def setUp(self):
        load()

    def test_film_by_title_when_no_ids(self):
        # fckg says "Volume 1", TMDB "Vol. 1".
        rows = award_data.film_records("tt0266697", 24, {"Kill Bill: Vol. 1"}, 2003)
        self.assertEqual([r["category"] for r in rows], ["Best Actress in a Leading Role"])
        self.assertEqual(award_data.film_records("tt0266697", 24, {"Kill Bill: Vol. 1"}, 1990), [])

    def test_film_by_id_not_title(self):
        self.assertEqual(len(award_data.film_records("tt28607951", None, {"Anora"}, 2024)), 3)
        self.assertEqual(award_data.film_records("tt9999999", None, {"Anora"}, 2024), [])

    def test_person(self):
        self.assertEqual(len(award_data.person_records("nm0048918", "Sean Baker")), 2)
        self.assertEqual(len(award_data.person_records("nm0000001", "Sean Baker")), 0)  # a namesake


class NamingTests(unittest.TestCase):
    def setUp(self):
        load()

    def test_film_rows_take_the_recorded_nominees(self):
        credits = {
            "cast": [{"id": 1, "name": "Mikey Madison", "gender": 1, "order": 0}],
            "crew": [{"id": 2, "name": "Sean Baker", "job": "Director"}],
        }
        tvdb = [
            {"award_name": "Academy Awards", "category_name": "Actress in a Leading Role", "year": "2025", "is_winner": False, "details": "", "person_name": None},
            # A stray: the Oscar records are complete and have no such nomination.
            {"award_name": "Academy Awards", "category_name": "Costume Design", "year": "2025", "is_winner": False, "details": "", "person_name": None},
        ]
        rows = _name_film_awards(tvdb, credits, [], award_data.film_records("tt28607951", None, {"Anora"}, 2024))
        by_cat = {r["category_name"]: r for r in rows}
        self.assertEqual(by_cat["Actress in a Leading Role"]["person_name"], "Mikey Madison")
        self.assertTrue(by_cat["Actress in a Leading Role"]["is_winner"])  # the record settles it
        self.assertEqual(by_cat["Actress in a Leading Role"]["person_ids"], [1])
        self.assertNotIn("Costume Design", by_cat)
        self.assertEqual(by_cat["Best Picture"]["person_name"], "Alex Coco, Samantha Quan & Sean Baker")
        self.assertEqual(by_cat["Best Film"]["person_ids"], [2])
        self.assertFalse(any(r["name_inferred"] for r in rows))

    def test_unrecorded_acting_row_is_dropped_not_guessed(self):
        credits = {"cast": [{"id": 3, "name": "Uma Thurman", "gender": 1, "order": 0},
                            {"id": 4, "name": "Lucy Liu", "gender": 1, "order": 1}], "crew": []}
        tvdb = [
            {"award_name": "BAFTA Awards", "category_name": "Best Leading Actress", "year": "2004", "is_winner": False, "details": "", "person_name": None},
            {"award_name": "BAFTA Awards", "category_name": "Best Supporting Actress", "year": "2004", "is_winner": False, "details": "", "person_name": None},
            # Not acting: kept, and named from the credits as before.
            {"award_name": "BAFTA Awards", "category_name": "Best Original Music", "year": "2004", "is_winner": False, "details": "", "person_name": None},
        ]
        rows = _name_film_awards(tvdb, credits, [], award_data.film_records("tt0266697", 24, {"Kill Bill: Vol. 1"}, 2003))
        self.assertEqual(sorted(r["category_name"] for r in rows), ["Best Leading Actress", "Best Original Music"])
        self.assertEqual(rows[0]["person_name"], "Uma Thurman")

    def test_show_rows_named_by_character(self):
        tvdb = [
            {"award_name": "Primetime Emmy Awards", "category_name": "Outstanding Supporting Actor in a Drama Series", "year": "2025",
             "is_winner": False, "details": 'For playing "Dylan George"', "person_name": None},
            # A Daytime Emmy is another award.
            {"award_name": "Daytime Emmy Awards", "category_name": "Outstanding Supporting Actor in a Drama Series", "year": "2025",
             "is_winner": False, "details": "", "person_name": None},
        ]
        rows = name_tv_awards(tvdb, tv_record_rows(award_data.show_records({"Severance"}, 2022, None)))
        primetime = [r for r in rows if r["award_name"] == "Primetime Emmy Awards"]
        self.assertEqual({r["person_name"] for r in primetime}, {"Zach Cherry", "Tramell Tillman"})
        self.assertEqual(len(primetime), 2)
        daytime = next(r for r in rows if r["award_name"] == "Daytime Emmy Awards")
        self.assertIsNone(daytime["person_name"])

    def test_person_row_needs_a_credit_when_matched_by_name(self):
        record = award_data.show_records({"Severance"}, 2022, None)[0]
        shows = {95396: {"title": "Severance", "original_title": "Severance", "year": 2022, "cast": True, "jobs": set()}}
        row = record_row(record, None, {}, shows)
        self.assertEqual((row["work_tmdb_id"], row["work_type"], row["on_record"]), (95396, "series", True))
        self.assertIsNone(record_row(record, None, {}, {}))  # someone else with the name


if __name__ == "__main__":
    unittest.main()
