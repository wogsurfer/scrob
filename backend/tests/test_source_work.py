import unittest

from core.source_work import _field, parse_source


class ParseSourceTests(unittest.TestCase):
    def test_based_on_template_gives_authors(self):
        self.assertEqual(
            parse_source("{{Based on|''[[Jaws (novel)|Jaws]]''|Peter Benchley}}"),
            (["Peter Benchley"], []),
        )

    def test_nested_templates_and_links(self):
        self.assertEqual(
            parse_source("{{Based on|''[[A Song of Ice and Fire]]''|{{Nowrap|[[George R. R. Martin]]}}}}"),
            (["George R. R. Martin"], []),
        )

    def test_several_authors(self):
        self.assertEqual(
            parse_source("{{Based on|''[[Watchmen]]''|[[Alan Moore]]|[[Dave Gibbons]]}}"),
            (["Alan Moore", "Dave Gibbons"], []),
        )

    def test_free_text_gives_linked_names(self):
        # Bones: "inspired_by" is prose with the author linked.
        self.assertEqual(
            parse_source("The life of forensic anthropologist and author [[Kathy Reichs]]"),
            ([], ["Kathy Reichs"]),
        )


class FieldTests(unittest.TestCase):
    WIKITEXT = (
        "{{Infobox television\n"
        "| creator = [[Hart Hanson]]\n"
        "| inspired_by = The life of [[Kathy Reichs|Reichs]] {{small|(author)}}\n"
        "| starring = {{Plainlist|\n* A\n* B\n}}\n"
        "}}"
    )

    def test_field_stops_at_next_parameter(self):
        self.assertEqual(_field(self.WIKITEXT, "inspired_by"), "The life of [[Kathy Reichs|Reichs]] {{small|(author)}}")

    def test_spaced_spelling_matches(self):
        self.assertIsNotNone(_field(self.WIKITEXT.replace("inspired_by", "inspired by"), "inspired_by"))

    def test_missing_field(self):
        self.assertIsNone(_field(self.WIKITEXT, "based_on"))


if __name__ == "__main__":
    unittest.main()
