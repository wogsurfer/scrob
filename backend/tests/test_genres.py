import unittest

from core.genres import strip_hidden_genres


class HiddenGenreTests(unittest.TestCase):
    def test_strips_kids_and_family_at_any_depth(self):
        data = {
            "genres": [{"id": 16, "name": "Animation"}, {"id": 10751, "name": "Family"}],
            "results": [{"title": "Up", "genre_ids": [16, 10751, 35]}, {"name": "Bluey", "genre_ids": [10762, 16]}],
            "parts": [{"genres": ["Kids", "Comedy"]}],
        }
        strip_hidden_genres(data)
        self.assertEqual(data["genres"], [{"id": 16, "name": "Animation"}])
        self.assertEqual(data["results"][0]["genre_ids"], [16, 35])
        self.assertEqual(data["results"][1]["genre_ids"], [16])
        self.assertEqual(data["parts"][0]["genres"], ["Comedy"])

    def test_leaves_everything_else_alone(self):
        data = {"title": "Family Plot", "genres": [{"id": 53, "name": "Thriller"}]}
        self.assertEqual(strip_hidden_genres(data), {"title": "Family Plot", "genres": [{"id": 53, "name": "Thriller"}]})


if __name__ == "__main__":
    unittest.main()
